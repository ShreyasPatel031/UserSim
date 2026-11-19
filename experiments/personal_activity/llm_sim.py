"""LLM simulator: Gemini (Vertex) reads a compact profile of the person, built
from train days only, and predicts the same targets as the other models.

- switch queries are batched (``batch`` per call) and sampled (``max_points``)
  from the test switches, so spend stays bounded;
- one call per test day for the daily shape and call slots;
- a hard USD budget is checked before every call (estimate) and after (actual).

Modes: ``off`` (skip), ``dry-run`` (write prompts + cost estimate, no calls),
``vertex`` (real calls with your own gcloud login, see GcloudVertex).

What leaves the machine in ``vertex`` mode: context labels (app names and
domains), clock times, durations and the derived profile below; no raw events.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from .metrics import median
from .models import DayPred, SwitchStats, _day_type_pool, _mean_shares, base_call_rate, rank
from .tasks import Dataset, DayStats, SwitchPoint, bucket_name, slot_clock

MODEL = "gemini-2.5-flash"
PRICE_IN, PRICE_OUT = 0.30, 2.50  # USD per 1M tokens (Vertex list price)
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

Caller = Callable[[str, str], Awaitable[dict[str, Any]]]

SYSTEM = (
    "You are a user simulator for ONE specific person. You are given a statistical "
    "profile of how this person uses their computer (apps and website domains, "
    "timing, idle breaks, calls), learned from their own past activity, and you "
    "predict what they do next. Use the profile; do not assume generic behaviour. "
    "Answer with JSON only, exactly in the requested shape. Only use context "
    "labels from the provided list."
)


def est_tokens(text: str) -> int:
    return math.ceil(len(text) / 3.5)


def est_cost(tokens_in: int, tokens_out: int) -> float:
    return tokens_in / 1e6 * PRICE_IN + tokens_out / 1e6 * PRICE_OUT


def _hhmm(hour: float) -> str:
    h = int(hour) % 24
    return f"{h:02d}:{int((hour - int(hour)) * 60):02d}"


def _mm(minutes: float) -> str:
    return _hhmm(minutes / 60)


@dataclass
class Budget:
    limit_usd: float
    spent_usd: float = 0.0
    calls: int = 0
    skipped: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    log: list[dict] = field(default_factory=list)

    def can_afford(self, est: float) -> bool:
        return self.spent_usd + est <= self.limit_usd


# --------------------------------------------------------------------------- prompts


def switch_profile(ds: Dataset, st: SwitchStats) -> str:
    tot_dur: Counter = Counter()
    for s in ds.segs(ds.train_days):
        tot_dur[s.lab] += s.dur
    T = sum(tot_dur.values()) or 1.0
    lines = ["CONTEXTS (share of active time | median dwell s | top next contexts with P):"]
    for lab in ds.labels:
        nxt = st.m1.get(lab, Counter())
        n = sum(nxt.values()) or 1
        top = ", ".join(f"{k} {v / n:.2f}" for k, v in nxt.most_common(4))
        d = median(st.dwell_lab.get(lab, []), 0)
        lines.append(f"- {lab} | {tot_dur[lab] / T:.3f} | {d:.0f} | {top}")
    lines.append("")
    lines.append(
        f"P(session ends with an idle break of >{ds.cfg.idle_gap_s / 60:.0f} min within "
        f"{ds.cfg.idle_horizon_min:.0f} min of a switch), by time of day:"
    )
    for hb in sorted(st.idle_hb):
        ys = st.idle_hb[hb]
        lines.append(f"- {bucket_name(hb)}: {sum(ys) / len(ys):.2f} (n={len(ys)})")
    ret = sum(1 for k, c in st.m2.items() for nx, v in c.items() if nx == k[0]) / max(1, sum(st.glob.values()))
    lines.append(f"Share of switches that go back to the previous context: {ret:.2f}")
    lines.append(f"Overall median dwell: {st.med_dwell:.0f} s")
    return "\n".join(lines)


def switch_query(p: SwitchPoint) -> dict:
    return {
        "id": p.id,
        "time": f"{WEEKDAYS[p.weekday]} {_hhmm(p.hour)}",
        "current": p.cur,
        "minutes_in_session": round(p.time_in_session / 60, 1),
        "earlier_today": [[lab, round((p.t - t0) / 60, 1), round(d)] for lab, t0, d in p.recent[-6:]],
    }


def switch_prompt(profile: str, labels: list[str], queries: list[dict], cfg) -> str:
    return (
        f"PROFILE (from this person's earlier days)\n{profile}\n\n"
        f"ALLOWED CONTEXT LABELS: {json.dumps(labels)}\n\n"
        "Each query is a moment when the person has just switched to `current`. "
        "`earlier_today` lists [context, minutes_ago_started, dwell_seconds], oldest first.\n"
        "For each query predict:\n"
        "- next: the 3 most likely contexts they switch to after `current` (most likely first, never `current`)\n"
        "- dwell_s: seconds they stay in `current` before switching or going idle (median guess)\n"
        f"- p_idle: probability they go idle (>{cfg.idle_gap_s / 60:.0f} min without input) within "
        f"{cfg.idle_horizon_min:.0f} minutes\n\n"
        f"QUERIES\n{json.dumps(queries, separators=(',', ':'))}\n\n"
        'Return {"predictions":[{"id":<int>,"next":[...3 labels],"dwell_s":<number>,"p_idle":<0..1>}, ...]} '
        "with one entry per query."
    )


def day_prompt(ds: Dataset, hist: list[DayStats], day: str, weekday: int) -> str:
    cfg = ds.cfg
    n_slots = ds.n_slots
    lines = [
        f"Predict the person's day on {WEEKDAYS[weekday]} {day}. Days start at "
        f"{cfg.day_start_hour:02d}:00 local time; all times are local.",
        "",
        "RECENT DAYS (most recent last): date weekday | first active | last active | "
        "active minutes | top shares | call slots",
    ]
    for d in hist[-14:]:
        top = ", ".join(f"{k} {v:.2f}" for k, v in sorted(d.shares.items(), key=lambda kv: -kv[1])[:5])
        calls = " ".join(slot_clock(s, cfg) for s in sorted(d.call_slots)) or "-"
        lines.append(
            f"- {d.day} {WEEKDAYS[d.weekday]} | {_mm(d.first_min)} | {_mm(d.last_min)} | "
            f"{d.active_min:.0f} | {top} | {calls}"
        )
    pool = _day_type_pool(hist, weekday >= 5)
    lines += [
        "",
        f"SAME DAY TYPE ({'weekend' if weekday >= 5 else 'weekday'}, n={len(pool)}): median first active "
        f"{_mm(median([d.first_min for d in pool]))}, median active {median([d.active_min for d in pool]):.0f} min",
        f"Mean share of time: {json.dumps({k: round(v, 3) for k, v in sorted(_mean_shares(pool).items(), key=lambda kv: -kv[1])})}",
        f"Call frequency per {cfg.slot_min}-min slot over all {len(hist)} past days (only slots that ever had a call):",
    ]
    base = base_call_rate(hist, n_slots)
    same_wd = [d for d in hist if d.weekday == weekday]
    for s in range(n_slots):
        k = sum(1 for d in hist if s in d.call_slots)
        if k:
            kw = sum(1 for d in same_wd if s in d.call_slots)
            lines.append(f"- {slot_clock(s, cfg)}: {k}/{len(hist)} days; on {WEEKDAYS[weekday]}s {kw}/{len(same_wd)}")
    lines += [
        "",
        f"ALLOWED CONTEXT LABELS: {json.dumps(ds.labels)}",
        "",
        'Return {"first_active":"HH:MM","total_active_min":<number>,'
        '"shares":{<label>:<fraction>, ... summing to 1},'
        '"call_slots":{"HH:MM":<probability of being on a call in that slot>, ...}} '
        f"where call_slots uses slot start times on the {cfg.slot_min}-minute grid and lists only slots with "
        f"probability >= 0.05 (others are taken as {base:.3f}).",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- parsing


def parse_switch(js: Any, labels: list[str]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    items = (js or {}).get("predictions") if isinstance(js, dict) else None
    for it in items or []:
        try:
            pid = int(it["id"])
        except (KeyError, TypeError, ValueError):
            continue
        nxt = [x for x in (it.get("next") or []) if isinstance(x, str) and x in labels]
        try:
            dwell = float(it.get("dwell_s"))
        except (TypeError, ValueError):
            dwell = None
        try:
            pi = min(1.0, max(0.0, float(it.get("p_idle"))))
        except (TypeError, ValueError):
            pi = None
        out[pid] = {"next": nxt, "dwell_s": dwell, "p_idle": pi}
    return out


def _parse_hhmm(s: str) -> float | None:
    try:
        h, m = str(s).strip().split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def parse_day(js: Any, ds: Dataset, fallback: DayPred) -> tuple[DayPred, bool]:
    if not isinstance(js, dict):
        return fallback, False
    cfg = ds.cfg
    fm = _parse_hhmm(js.get("first_active", ""))
    if fm is not None and fm < cfg.day_start_hour * 60:
        fm += 24 * 60
    try:
        am = float(js.get("total_active_min"))
    except (TypeError, ValueError):
        am = None
    shares = {k: float(v) for k, v in (js.get("shares") or {}).items() if k in ds.labels and _num(v)}
    z = sum(shares.values())
    shares = {k: v / z for k, v in shares.items()} if z > 0 else fallback.shares
    base = min(fallback.call_p) if fallback.call_p else 0.01
    call_p = [base] * ds.n_slots
    for k, v in (js.get("call_slots") or {}).items():
        m = _parse_hhmm(k)
        if m is None or not _num(v):
            continue
        idx = int(((m - cfg.day_start_hour * 60) % (24 * 60)) // cfg.slot_min)
        if 0 <= idx < ds.n_slots:
            call_p[idx] = min(1.0, max(0.0, float(v)))
    ok = fm is not None and am is not None
    return DayPred(fm if fm is not None else fallback.first_min, am if am is not None else fallback.active_min,
                   shares, call_p), ok


def _num(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------- runner


class GcloudVertex:
    """Gemini on Vertex with the caller's own gcloud login (stdlib only).

    Token: ``gcloud auth print-access-token`` (active account), re-minted on 401
    and every 45 min. Project: --llm-project, else $GOOGLE_CLOUD_PROJECT, else
    ``gcloud config get-value project``."""

    def __init__(self, project: str | None = None, location: str = "us-central1", model: str = MODEL):
        self.project = project or os.environ.get("GOOGLE_CLOUD_PROJECT") or _gcloud_out("config", "get-value", "project")
        self.account = _gcloud_out("config", "get-value", "account")
        self.location = location
        self.model = model
        self._token: str | None = None
        self._token_t = 0.0

    @classmethod
    def available(cls, project: str | None = None) -> tuple[bool, str]:
        if shutil.which("gcloud") is None:
            return False, "gcloud not installed"
        if not _gcloud_out("auth", "print-access-token"):
            return False, "no gcloud login (run: gcloud auth login)"
        proj = project or os.environ.get("GOOGLE_CLOUD_PROJECT") or _gcloud_out("config", "get-value", "project")
        if not proj:
            return False, "no project (pass --llm-project or: gcloud config set project <id>)"
        return True, proj

    def _tok(self, force: bool = False) -> str:
        if force or not self._token or time.time() - self._token_t > 45 * 60:
            self._token = _gcloud_out("auth", "print-access-token")
            self._token_t = time.time()
        if not self._token:
            raise RuntimeError("gcloud auth print-access-token returned nothing")
        return self._token

    def _url(self) -> str:
        loc = self.location
        host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
        return (f"https://{host}/v1/projects/{self.project}/locations/{loc}"
                f"/publishers/google/models/{self.model}:generateContent")

    def _post(self, prompt: str, system: str) -> dict[str, Any]:
        body = json.dumps({
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json",
                                 "thinkingConfig": {"thinkingBudget": 0}},
        }).encode()
        force = False
        for attempt in range(6):
            req = urllib.request.Request(self._url(), data=body, method="POST", headers={
                "Authorization": f"Bearer {self._tok(force)}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt < 5:
                    force = True
                    continue
                if e.code in (429, 500, 503) and attempt < 5:
                    time.sleep(5 * 2**attempt)
                    continue
                raise RuntimeError(f"Vertex HTTP {e.code}: {e.read()[:300]!r}") from e
        raise RuntimeError("Vertex request failed after retries")

    async def __call__(self, prompt: str, system: str) -> dict[str, Any]:
        data = await asyncio.to_thread(self._post, prompt, system)
        text = ""
        for cand in data.get("candidates") or []:
            text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts") or []).strip()
            if text:
                break
        u = data.get("usageMetadata") or {}
        tin = int(u.get("promptTokenCount") or 0)
        tout = int(u.get("candidatesTokenCount") or 0) + int(u.get("thoughtsTokenCount") or 0)
        try:
            js = json.loads(text) if text else None
        except ValueError:
            js = None
        return {"text": text, "json": js, "model": data.get("modelVersion") or self.model,
                "usage": {"input_tokens": tin, "output_tokens": tout, "cost_usd": est_cost(tin, tout)}}


def _gcloud_out(*args: str) -> str:
    if shutil.which("gcloud") is None:
        return ""
    try:
        r = subprocess.run(["gcloud", *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    out = r.stdout.strip() if r.returncode == 0 else ""
    return "" if out == "(unset)" else out


@dataclass
class LLMResult:
    switch: dict[int, dict]  # point id -> prediction
    sample_ids: list[int]
    days: dict[str, DayPred]
    days_ok: dict[str, bool]
    budget: Budget
    mode: str
    est_cost_usd: float


class LLMSimulator:
    def __init__(
        self,
        ds: Dataset,
        *,
        mode: str = "off",
        caller: Caller | None = None,
        budget_usd: float = 1.0,
        max_points: int = 200,
        batch: int = 20,
        concurrency: int = 4,
        out_dir: Path | None = None,
        seed: int = 0,
    ):
        self.ds = ds
        self.mode = mode
        self.caller = caller
        self.budget = Budget(budget_usd)
        self.max_points = max_points
        self.batch = batch
        self.concurrency = concurrency
        self.out_dir = out_dir
        self.seed = seed

    def sample(self, pts: list[SwitchPoint]) -> list[SwitchPoint]:
        cand = [p for p in pts if p.next is not None]
        if len(cand) <= self.max_points:
            return cand
        rng = random.Random(self.seed)
        return sorted(rng.sample(cand, self.max_points), key=lambda p: p.t)

    def plan(self, st: SwitchStats, test_pts: list[SwitchPoint], day_jobs: list[tuple[str, list[DayStats], int]]):
        profile = switch_profile(self.ds, st)
        sample = self.sample(test_pts)
        jobs: list[tuple[str, str, Any]] = []
        for i in range(0, len(sample), self.batch):
            chunk = sample[i : i + self.batch]
            prompt = switch_prompt(profile, self.ds.labels, [switch_query(p) for p in chunk], self.ds.cfg)
            jobs.append(("switch", prompt, [p.id for p in chunk]))
        for day, hist, wd in day_jobs:
            jobs.append(("day", day_prompt(self.ds, hist, day, wd), day))
        return sample, jobs

    @staticmethod
    def _job_est(kind: str, prompt: str, payload) -> float:
        out_tok = 45 * len(payload) if kind == "switch" else 700
        return est_cost(est_tokens(SYSTEM) + est_tokens(prompt), out_tok)

    async def run(
        self, st: SwitchStats, test_pts: list[SwitchPoint], day_jobs: list[tuple[str, list[DayStats], int]],
        day_fallback: Callable[[str], DayPred],
    ) -> LLMResult:
        sample, jobs = self.plan(st, test_pts, day_jobs)
        est = sum(self._job_est(*j) for j in jobs)
        res = LLMResult({}, [p.id for p in sample], {}, {}, self.budget, self.mode, est)
        if self.out_dir is not None:
            pdir = self.out_dir / "llm_prompts"
            pdir.mkdir(parents=True, exist_ok=True)
            for i, (kind, prompt, _payload) in enumerate(jobs):
                (pdir / f"{i:03d}_{kind}.txt").write_text(SYSTEM + "\n\n" + prompt)
        if self.mode != "vertex" or not jobs:
            return res
        if self.caller is None:
            self.caller = GcloudVertex()
        sem = asyncio.Semaphore(self.concurrency)

        async def do(kind: str, prompt: str, payload):
            async with sem:
                e = self._job_est(kind, prompt, payload)
                if not self.budget.can_afford(e):
                    self.budget.skipped += 1
                    return
                self.budget.spent_usd += e  # reserve; corrected with actual usage below
                try:
                    r = await self.caller(prompt, SYSTEM)
                except Exception as exc:  # noqa: BLE001 - one failed batch must not sink the run
                    self.budget.spent_usd -= e
                    self.budget.log.append({"kind": kind, "error": repr(exc)[:300]})
                    return
                u = r.get("usage") or {}
                actual = float(u.get("cost_usd") or e)
                self.budget.spent_usd += actual - e
                self.budget.calls += 1
                self.budget.tokens_in += int(u.get("input_tokens") or 0)
                self.budget.tokens_out += int(u.get("output_tokens") or 0)
                self.budget.log.append({"kind": kind, "cost_usd": actual, "model": r.get("model")})
                js = r.get("json")
                if js is None and r.get("text"):
                    try:
                        js = json.loads(r["text"])
                    except ValueError:
                        js = None
                if kind == "switch":
                    res.switch.update(parse_switch(js, self.ds.labels))
                else:
                    pred, ok = parse_day(js, self.ds, day_fallback(payload))
                    res.days[payload] = pred
                    res.days_ok[payload] = ok

        await asyncio.gather(*(do(*j) for j in jobs))
        return res


def llm_next_rank(pred: dict | None, fill: list[str], cur: str) -> list[str]:
    """LLM's ranking, padded with the most-frequent order (marked in the report)."""
    return rank({}, (pred or {}).get("next", []) + fill, cur)


__all__ = ["LLMSimulator", "LLMResult", "llm_next_rank"]
