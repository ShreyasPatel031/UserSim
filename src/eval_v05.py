"""UserSim v0.5: teacher-forced STOP/CONTINUE on Mind2Web human states."""

from __future__ import annotations

import json
import math
import random
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cache import get as cache_get
from cache import put as cache_put
from config import MODEL, RESULTS_DIR, WORKERS
from model import TokenMeter, _client
from google.genai import types
from stats import mean
from stop_dataset import (
    AGENT_SYSTEM,
    HUMAN_SYSTEM,
    build_user_prompt,
    load_stop_steps,
    sanity_check,
)

CONDITIONS = {
    "agent": AGENT_SYSTEM,
    "human_sim": HUMAN_SYSTEM,
}


@dataclass
class StopResult:
    decision: str | None
    p_stop: float | None
    raw: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


def _parse(raw: str) -> tuple[str | None, float | None]:
    if not raw:
        return None, None
    match = re.search(r"\{.*\}", raw.strip(), re.S)
    blob = match.group(0) if match else raw.strip()
    try:
        obj = json.loads(blob)
    except json.JSONDecodeError:
        return None, None
    decision = obj.get("decision")
    if isinstance(decision, str):
        decision = decision.strip().upper()
        if decision not in {"STOP", "CONTINUE"}:
            decision = None
    else:
        decision = None
    p = obj.get("p_stop")
    try:
        p = float(p)
        p = min(1.0, max(0.0, p))
    except (TypeError, ValueError):
        p = None
    if decision is None and p is not None:
        decision = "STOP" if p >= 0.5 else "CONTINUE"
    if p is None and decision is not None:
        p = 0.85 if decision == "STOP" else 0.15
    return decision, p


def predict_stop(prompt: str, system: str, condition: str, client) -> StopResult:
    payload = {"model": MODEL, "condition": condition, "system": system, "prompt": prompt}
    cached = cache_get(payload)
    if cached:
        return StopResult(**cached)
    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0,
                max_output_tokens=64,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                response_mime_type="application/json",
            ),
        )
        raw = resp.text or ""
        usage = resp.usage_metadata
        decision, p_stop = _parse(raw)
        result = StopResult(
            decision=decision,
            p_stop=p_stop,
            raw=raw,
            prompt_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
        )
    except Exception as exc:  # noqa: BLE001
        result = StopResult(None, None, "", error=str(exc)[:400])
    if result.error is None:
        cache_put(payload, asdict(result))
    return result


def run_condition(steps: list[dict], condition: str) -> tuple[list[dict], TokenMeter]:
    client = _client()
    system = CONDITIONS[condition]
    meter = TokenMeter()
    out = [None] * len(steps)

    def one(idx: int, step: dict):
        prompt = build_user_prompt(step)
        pred = predict_stop(prompt, system, condition, client)
        return idx, pred

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = [pool.submit(one, i, s) for i, s in enumerate(steps)]
        done = 0
        for fut in as_completed(futs):
            idx, pred = fut.result()
            meter.add(pred)
            step = steps[idx]
            decision = pred.decision or "CONTINUE"
            p_stop = 0.5 if pred.p_stop is None else pred.p_stop
            out[idx] = {
                **{k: step[k] for k in (
                    "annotation_id", "website", "domain", "task", "step_index",
                    "n_steps", "is_terminal", "label", "gold_op", "gold_repr",
                )},
                "condition": condition,
                "pred": decision,
                "p_stop": p_stop,
                "raw": pred.raw,
                "error": pred.error,
                "prompt_tokens": pred.prompt_tokens,
                "output_tokens": pred.output_tokens,
                "history_len": len(step["history"]),
            }
            done += 1
            if done % 40 == 0 or done == len(steps):
                print(f"  {condition:10s} {done}/{len(steps)}  cost=${meter.cost_usd:.3f}", flush=True)
    return out, meter


def group(rows: list[dict]) -> dict[str, list[dict]]:
    g = defaultdict(list)
    for r in rows:
        g[r["annotation_id"]].append(r)
    for tid in g:
        g[tid] = sorted(g[tid], key=lambda r: r["step_index"])
    return dict(g)


def clip01(p: float) -> float:
    return min(1 - 1e-6, max(1e-6, p))


def expected_length(traj_rows: list[dict]) -> float:
    rows = sorted(traj_rows, key=lambda r: r["step_index"])
    t_len = len(rows)
    s = 1.0
    expected = 0.0
    for t, r in enumerate(rows, start=1):
        h = clip01(float(r["p_stop"]))
        expected += t * s * h
        s *= 1.0 - h
    expected += (t_len + 1) * s
    return expected


def classification(rows: list[dict]) -> dict:
    y = [r["label"] == "STOP" for r in rows]
    yhat = [r["pred"] == "STOP" for r in rows]
    tp = sum(a and b for a, b in zip(y, yhat))
    fp = sum((not a) and b for a, b in zip(y, yhat))
    fn = sum(a and (not b) for a, b in zip(y, yhat))
    tn = sum((not a) and (not b) for a, b in zip(y, yhat))
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    spec = tn / (tn + fp) if tn + fp else 0.0
    return {
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "balanced_accuracy": 0.5 * (rec + spec),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def brier(rows: list[dict]) -> float:
    return mean([(float(r["p_stop"]) - (1.0 if r["label"] == "STOP" else 0.0)) ** 2 for r in rows])


def log_loss(rows: list[dict]) -> float:
    total = 0.0
    for r in rows:
        y = 1.0 if r["label"] == "STOP" else 0.0
        p = clip01(float(r["p_stop"]))
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(rows) if rows else 0.0


def progress_bin(row: dict) -> str:
    if row["is_terminal"]:
        return "terminal"
    frac = (row["step_index"] + 1) / row["n_steps"]
    if frac <= 0.25:
        return "0-25%"
    if frac <= 0.50:
        return "25-50%"
    if frac <= 0.75:
        return "50-75%"
    return "75-100%"


def length_bin(n: int) -> str:
    if n <= 5:
        return "short"
    if n <= 10:
        return "medium"
    return "long"


def traj_metrics(rows: list[dict]) -> dict:
    g = group(rows)
    term = [r for r in rows if r["is_terminal"]]
    nonterm = [r for r in rows if not r["is_terminal"]]
    cls = classification(rows)
    ratios = []
    errors = []
    for tid, tr in g.items():
        actual = tr[-1]["n_steps"]
        pred_len = expected_length(tr)
        ratios.append(pred_len / actual)
        errors.append(pred_len - actual)
    return {
        "n_steps": len(rows),
        "n_trajectories": len(g),
        "terminal_continue_rate": mean([r["pred"] == "CONTINUE" for r in term]),
        "stop_recall": mean([r["pred"] == "STOP" for r in term]),
        "premature_stop_rate": mean([r["pred"] == "STOP" for r in nonterm]),
        "mean_p_stop_terminal": mean([float(r["p_stop"]) for r in term]),
        "mean_p_stop_nonterminal": mean([float(r["p_stop"]) for r in nonterm]),
        "brier": brier(rows),
        "log_loss": log_loss(rows),
        "length_ratio": mean(ratios),
        "mean_terminal_step_error": mean(errors),
        "stop_late_rate": mean([e > 0.05 for e in errors]),
        "stop_early_rate": mean([e < -0.05 for e in errors]),
        "errors_api": sum(1 for r in rows if r.get("error")),
        **cls,
    }


def bootstrap_fn(rows: list[dict], fn, n: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Resample trajectories with replacement. Duplicate tasks stay as copies."""
    g = group(rows)
    ids = list(g)
    point = fn(rows)
    rng = random.Random(seed)
    stats = []
    for _ in range(n):
        sampled = [ids[rng.randrange(len(ids))] for _ in ids]
        pooled = []
        for i, tid in enumerate(sampled):
            copy_id = f"{tid}#{i}"
            for row in g[tid]:
                pooled.append({**row, "annotation_id": copy_id})
        stats.append(fn(pooled))
    stats.sort()
    return point, stats[int(0.025 * n)], stats[min(len(stats) - 1, int(0.975 * n))]


def bootstrap_delta(rows_a, rows_b, fn, n: int = 2000, seed: int = 0):
    ga, gb = group(rows_a), group(rows_b)
    ids = sorted(set(ga) & set(gb))
    point = fn(rows_a) - fn(rows_b)
    rng = random.Random(seed)
    stats = []
    for _ in range(n):
        sampled = [ids[rng.randrange(len(ids))] for _ in ids]
        a, b = [], []
        for i, tid in enumerate(sampled):
            copy_id = f"{tid}#{i}"
            a.extend({**row, "annotation_id": copy_id} for row in ga[tid])
            b.extend({**row, "annotation_id": copy_id} for row in gb[tid])
        stats.append(fn(a) - fn(b))
    stats.sort()
    return point, stats[int(0.025 * n)], stats[min(len(stats) - 1, int(0.975 * n))]


def calibration_bins(rows: list[dict], k: int = 5) -> list[dict]:
    edges = [i / k for i in range(k + 1)]
    out = []
    for i in range(k):
        lo, hi = edges[i], edges[i + 1]
        if i == k - 1:
            bucket = [r for r in rows if lo <= float(r["p_stop"]) <= hi]
        else:
            bucket = [r for r in rows if lo <= float(r["p_stop"]) < hi]
        if not bucket:
            continue
        out.append(
            {
                "bin": f"{lo:.1f}–{hi:.1f}",
                "n": len(bucket),
                "mean_p": mean([float(r["p_stop"]) for r in bucket]),
                "frac_stop": mean([r["label"] == "STOP" for r in bucket]),
            }
        )
    return out
    buckets = defaultdict(list)
    for r in rows:
        buckets[key_fn(r)].append(r)
    out = {}
    for k, rs in sorted(buckets.items(), key=lambda kv: str(kv[0])):
        out[str(k)] = {
            "n": len(rs),
            "p_stop": mean([float(r["p_stop"]) for r in rs]),
            "pred_stop_rate": mean([r["pred"] == "STOP" for r in rs]),
            "true_stop_rate": mean([r["label"] == "STOP" for r in rs]),
        }
    return out


def slice_continue_p(rows: list[dict], key_fn) -> dict:
    buckets = defaultdict(list)
    for r in rows:
        buckets[key_fn(r)].append(r)
    out = {}
    for k, rs in sorted(buckets.items(), key=lambda kv: str(kv[0])):
        out[str(k)] = {
            "n": len(rs),
            "p_stop": mean([float(r["p_stop"]) for r in rs]),
            "pred_stop_rate": mean([r["pred"] == "STOP" for r in rs]),
            "true_stop_rate": mean([r["label"] == "STOP" for r in rs]),
        }
    return out


def pick_examples(agent_rows, sim_rows) -> dict:
    paired = list(zip(agent_rows, sim_rows))
    hyper = [
        {
            "task": a["task"],
            "website": a["website"],
            "domain": a["domain"],
            "last_action": a["gold_repr"],
            "n_steps": a["n_steps"],
            "agent": a["pred"],
            "agent_p_stop": a["p_stop"],
            "human_sim": s["pred"],
            "human_sim_p_stop": s["p_stop"],
        }
        for a, s in paired
        if a["is_terminal"] and a["pred"] == "CONTINUE" and s["pred"] == "STOP"
    ]
    both_hyper = [
        {
            "task": a["task"],
            "website": a["website"],
            "last_action": a["gold_repr"],
            "n_steps": a["n_steps"],
            "agent_p_stop": a["p_stop"],
            "human_sim_p_stop": s["p_stop"],
        }
        for a, s in paired
        if a["is_terminal"] and a["pred"] == "CONTINUE" and s["pred"] == "CONTINUE"
    ]
    premature = [
        {
            "task": s["task"],
            "website": s["website"],
            "action": s["gold_repr"],
            "step_index": s["step_index"],
            "n_steps": s["n_steps"],
            "agent": a["pred"],
            "human_sim": s["pred"],
            "human_sim_p_stop": s["p_stop"],
        }
        for a, s in paired
        if (not s["is_terminal"]) and s["pred"] == "STOP"
    ]
    both_stop = [
        {
            "task": a["task"],
            "website": a["website"],
            "last_action": a["gold_repr"],
            "agent_p_stop": a["p_stop"],
            "human_sim_p_stop": s["p_stop"],
        }
        for a, s in paired
        if a["is_terminal"] and a["pred"] == "STOP" and s["pred"] == "STOP"
    ]
    return {
        "hyperactivity_agent_only": hyper[:4],
        "hyperactivity_both": both_hyper[:3],
        "premature_human_sim": premature[:4],
        "both_correct_stop": both_stop[:3],
    }


def summarize(name: str, rows: list[dict], seed: int) -> dict:
    m = traj_metrics(rows)
    mapping = {
        "terminal_continue_rate": 1,
        "premature_stop_rate": 2,
        "f1": 3,
        "balanced_accuracy": 4,
        "length_ratio": 5,
        "mean_p_stop_terminal": 6,
        "mean_p_stop_nonterminal": 7,
    }
    ci = {}
    for key, off in mapping.items():
        _, lo, hi = bootstrap_fn(rows, lambda rs, k=key: traj_metrics(rs)[k], seed=seed + off)
        ci[key] = [lo, hi]
    return {
        **m,
        "ci95_clustered": ci,
        "by_progress": slice_continue_p(rows, progress_bin),
        "by_length": slice_continue_p(rows, lambda r: length_bin(r["n_steps"])),
        "by_domain": slice_continue_p(rows, lambda r: r.get("domain") or "Other"),
        "by_prev_op": slice_continue_p(rows, lambda r: r.get("gold_op") or "?"),
        "calibration": calibration_bins(rows),
    }


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    steps = load_stop_steps()
    problems = sanity_check(steps)
    n_traj = len({s["annotation_id"] for s in steps})
    n_stop = sum(1 for s in steps if s["label"] == "STOP")
    print(f"v0.5 steps={len(steps)} traj={n_traj} STOP={n_stop} CONTINUE={len(steps)-n_stop}")
    print(f"sanity issues: {len(problems)}")
    for p in problems[:20]:
        print("  SANITY", p)
    if problems:
        raise SystemExit("sanity checks failed; not calling Vertex")

    # framing isolation
    assert AGENT_SYSTEM != HUMAN_SYSTEM
    sample = build_user_prompt(steps[0])
    assert "successfully complete" not in sample.lower()
    print("sanity ok. sample prompt follows:\n---")
    print(sample[:900])
    print("---")

    predictions = {}
    spend = {}
    for cond in ["agent", "human_sim"]:
        print(f"running {cond}")
        rows, meter = run_condition(steps, cond)
        predictions[cond] = rows
        spend[cond] = {
            "usd": round(meter.cost_usd, 4),
            "calls": meter.calls,
            "prompt_tokens": meter.prompt_tokens,
            "output_tokens": meter.output_tokens,
        }
        (RESULTS_DIR / f"predictions_v05_{cond}.json").write_text(json.dumps(rows, indent=2))

    agent, sim = predictions["agent"], predictions["human_sim"]
    summary = {
        "question": "Do agents continue acting after a human demonstration would stop?",
        "label": "teacher-forced STOP/CONTINUE on human states, not free-running trajectories",
        "model": MODEL,
        "n_steps": len(steps),
        "n_trajectories": n_traj,
        "bootstrap": "cluster by trajectory, 2000 resamples",
        "sft_condition": "skipped — no checkpoint in this repo",
        "agent": summarize("agent", agent, seed=10),
        "human_sim": summarize("human_sim", sim, seed=20),
        "delta_agent_minus_human_sim": {},
        "examples": pick_examples(agent, sim),
        "spend_usd": {
            **spend,
            "total": round(sum(v["usd"] for v in spend.values()), 4),
        },
    }
    for key in [
        "terminal_continue_rate",
        "premature_stop_rate",
        "f1",
        "length_ratio",
        "mean_p_stop_terminal",
    ]:
        d, lo, hi = bootstrap_delta(
            agent, sim, lambda rs, k=key: traj_metrics(rs)[k], seed=30 + len(key)
        )
        summary["delta_agent_minus_human_sim"][key] = {
            "delta": d,
            "ci95_clustered": [lo, hi],
        }

    (RESULTS_DIR / "summary_v05.json").write_text(json.dumps(summary, indent=2))
    slim = {k: summary[k] for k in summary if k != "examples"}
    print(json.dumps(slim, indent=2))


if __name__ == "__main__":
    main()
