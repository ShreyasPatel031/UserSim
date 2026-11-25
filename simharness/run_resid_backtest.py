"""RESID-BACKTEST-1: the nightly simulation lines, replayed on 2026 backtest days (after Gemini 2.5 Flash's cutoff).

  python -m simharness.run_resid_backtest run   --bench BENCH --days D1,D2,... --work WORK [--budget 20] [--sync gs://prefix]
  python -m simharness.run_resid_backtest score --work WORK [--leaderboard gs://.../residual_leaderboard.json]

Lines (gemini-2.5-flash, temperature and prompts as in E5's nightly code on origin/claude/person-model-v2, a32d4d9a):
  stageb_v1   experiments/simlab/cohort_calibration/rerank_b.py: per launch, agents answer yes/no + p + sentiment.
              Scores: yes_share, mean_p, sentiment (pos - neg share).
  stageb_v2   rerank_b2.py: one call per person over the whole shortlist (shuffled by md5(person + D)), picks k = their
              own upvotes per active day (1-5). Score: pick_share.
  person_panel person_panel.py without the launch-page block (see below): the run_what_panel selection (top 30 by topic
              share), a fixed md5(launch + D) draw, one temperature-0.7 call each, the same privacy guard.
              Score: mean VADER compound of the kept comments. The deployed prompt asks for a comment only, so there is
              no "would upvote / use" share to read from this line.
  The persona panel is not replayed (it needs the day's segment profiles, which were not built for 2026 backtest days).

Leak rules: every history comes from the benchmark tables (simharness bench_v0): upvotes on launches dated before D
(upvotes are undated snapshots attributed to the launch day) and comments on launches before D written before D
starts. Launch text is the benchmark item as listed at the start of its day (name, tagline, description, topics). No
launch-day comment or vote is read. The launch-page block (maker's first comment) is NOT available for backtest days
(no maker ids or comment times held for Apr-Oct launches), so the person panel runs as the no-block shadow.

Differences from the nightly jobs, forced by the backtest (all flagged in the outputs):
  * the backer_top draw: E5 samples from the top 200 of the CF backer list (backer_pred_v2), which does not exist for
    these days. Here the top 200 are ranked by the same rule as the person-panel selection (topic share of the
    person's past upvotes for the launch's topics, ties by 30-day upvotes), among active people.
  * scale: agents per launch and panel size are set by --v1-top/--v1-rand/--panel (nightly: 50 / 20 / 15) to fit
    the budget; the prompts and aggregation rules are unchanged.
  * survivorship: the held people were chosen in Oct-Nov 2026, after every backtest day. Each line is also scored on
    "established" agents only (first held upvote at least 60 days before D) as a check; it cannot remove the bias.

Per day, WORK/days/<D>.json holds per-launch scores (no person ids); WORK/private/<D>.parquet holds prompts, raw
answers and salted person ids (private: copy only to the private bucket).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

import numpy as np
import pandas as pd

from simharness.bench import Benchmark, day_ord, scrub as bench_scrub
from simharness.finetune.export import FT_PROMPT
from simharness.task_c import _item_fields
from simharness.bench import Item

B = "gs://usersim-bakeoff-347838016394/usersim_sim"
TOPN = 15

# ---------------------------------------------------------------- model (E5's sim_model.py, gemini-2.5-flash on Vertex)
MODEL = "gemini-2.5-flash"
_URL = "https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/{m}:generateContent"
USAGE = {"in": 0, "out": 0, "calls": 0}
_tok = {"t": "", "at": 0}
_lk = threading.Lock()
BUDGET = {"usd": 20.0}


class BudgetExceeded(Exception):
    pass


def _token():
    with _lk:
        if time.time() - _tok["at"] > 1800:
            _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
            _tok["at"] = time.time()
        return _tok["t"]


def usd():
    return USAGE["in"] / 1e6 * 0.30 + USAGE["out"] / 1e6 * 2.50


def call(prompt, max_tokens=300, temperature=0.0):
    if usd() >= BUDGET["usd"]:
        raise BudgetExceeded()
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens,
                                 "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}}
    for i in range(6):
        try:
            req = urllib.request.Request(_URL.format(m=MODEL), json.dumps(body).encode(),
                                         {"Authorization": "Bearer " + _token(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                j = json.load(r)
                u = j.get("usageMetadata", {})
                with _lk:
                    USAGE["in"] += u.get("promptTokenCount", 0)
                    USAGE["out"] += u.get("candidatesTokenCount", 0)
                    USAGE["calls"] += 1
                return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        except Exception as e:  # noqa: BLE001
            if "403" in str(e) or "PERMISSION" in str(e).upper():
                raise
            time.sleep(5 * (i + 1))
    return ""


# ---------------------------------------------------------------- prompts, verbatim from E5 (a32d4d9a)
PROMPT_V1 = """You are simulating one specific, real Product Hunt user. Everything you know about them is their own activity below.
Launches they upvoted recently (newest first):
{ups}
{cms}
Today this launch appears on Product Hunt:
{page}

{rate}
Would this person upvote this one today? Answer as this person, keeping their usual rate in mind.
JSON only: {{"vote": "yes"|"no", "p": <0-100 probability they upvote>, "comment": "<one line they might write, in their voice>", "sentiment": "pos"|"neu"|"neg"}}"""
PROMPT_V2 = """You are simulating one specific, real Product Hunt user. Everything you know about them is their own activity below.
Launches they upvoted recently (newest first):
{ups}
{cms}
Today these launches are on Product Hunt:
{lst}

On days they are active this person upvotes about {k} launch(es). Pick exactly the {k} launch(es) above this person would most likely upvote today.
JSON only: {{"picks": [<launch numbers>], "comment_on_first_pick": "<one line in their voice>"}}"""
OLD = "This member did comment on this launch today. Write that comment as they would: their usual length, tone, focus and\nkind of question or praise, as their past comments show. Reply with the comment only."
NEW = ("This member did comment on this launch today. Write that comment as they would: their usual length, tone, focus and\nkind of question or praise, as their past comments show. "
       "Do not mention your own name, employer or products. Answer in JSON only: {\"comment\": \"...\"}")
MAKER = re.compile(r"\b(we built|we('| a)re (excited|thrilled|launching)|our (team|launch|product)|thanks for (the )?(support|hunting)|i built|we launched|hunting us|my (startup|company|product)|co-?founder|founder of|maker of|(hey|hi|hello) product hunt|i'?m \w+,? (the )?(co-?founder|founder|maker|ceo|cto)|we('ve| have) (built|been building)|our (users|customers|app|tool|platform))\b", re.I)
SELFNAME = re.compile(r"\b[A-Z][a-z]{2,} here\b|\b(I'?m|I am|my name is) [A-Z][a-z]{2,}\b(?! (excited|glad|happy|curious|interested|impressed))")


def scrub(s):  # E5's scrub
    return re.sub(r"\s+", " ", re.sub(r"@[A-Za-z0-9_]{2,}", "", str(s)))[:220]


def own_names(prompt):
    h = prompt.split("TODAY'S LAUNCH:")[0]
    names = set()
    for m in re.finditer(r"^- \d{4}-\d{2}-\d{2}: (.+?) \|", h, re.M):
        names.add(m.group(1).strip())
    for m in re.finditer(r'^- on (.+?): "', h, re.M):
        names.add(m.group(1).strip())
    out = set()
    for n in names:
        out.add(n)
        w = re.split(r"[\s:+|-]", n)[0]
        if len(w) >= 5 and w.lower() not in {"smart", "super", "simple", "better", "first", "agent", "open", "cloud", "build", "magic"}:
            out.add(w)
    return {n for n in out if len(n) >= 4}


# ---------------------------------------------------------------- one day
class Day:
    def __init__(self, bench: Benchmark, D: str, args):
        self.b, self.D, self.a = bench, D, args
        self.o = day_ord(D)
        S = json.loads(subprocess.run(["gsutil", "cat", f"{B}/results/structural/backtest/{D}.json"], capture_output=True).stdout)
        self.structural_model = S.get("structural_model")
        self.truth = {str(k): int(v["final_rank"]) for k, v in S["truth"]["by_id"].items()}
        self.short = [{"id": str(x["id"]), "srank": int(x["structural_rank"])}
                      for x in sorted(S["launches"], key=lambda r: r["structural_rank"])[:TOPN]]
        it = bench.items
        self.idx_of = dict(zip(it["item_id"].astype(str), it["item_idx"]))
        self.INFO = {int(i): (t, s, list(g)) for i, t, s, g in zip(it["item_idx"], it["title"], it["summary"], it["tags"])}
        self.items = {x["id"]: bench.item(self.idx_of[x["id"]]) for x in self.short if x["id"] in self.idx_of}
        st = bench.state(D)
        self.st = st
        pool = bench.pool(D)
        self.active = np.array(sorted(p for p in pool if st["n30"][p] >= 1))
        h = bench.hist
        e = h[(h["kind"] == 0) & (h["day_ord"] < self.o)]
        e30 = e[e["day_ord"] >= self.o - 30]
        g = e30.groupby("person_idx")
        self.VR = (g.size() / g["day_ord"].nunique()).to_dict()
        self.first = e.groupby("person_idx")["day_ord"].min().to_dict()
        self.E = e
        c = bench.comments
        start = pd.Timestamp(D, tz="America/Los_Angeles").tz_convert("UTC")
        ts = pd.to_datetime(c["ts"], utc=True)
        self.C = c[(c["day_ord"] < self.o) & (ts.isna() | (ts < start))]   # comments on earlier launches, written before D starts

    def ups(self, p):
        x = self.E[self.E["person_idx"] == p].sort_values(["day_ord", "item_idx"], ascending=False).drop_duplicates("item_idx").head(30)
        return "\n".join(f"- {self.INFO[i][0]} - {self.INFO[i][1]} [{', '.join(self.INFO[i][2])}]" for i in x["item_idx"]) or "- (no upvotes visible)"

    def cms(self, p):
        x = self.C[self.C["person_idx"] == p].sort_values("day_ord", ascending=False).head(5)
        L = [f"on {self.INFO[i][0]}: \"{scrub(t)}\"" for i, t in zip(x["item_idx"], x["text"]) if i in self.INFO]
        return ("Their own past comments:\n" + "\n".join(f"- {c}" for c in L)) if L else ""

    def backer_top(self, item):
        """Stand-in for E5's CF backer list: top 200 active people by topic share for the launch's topics, ties by n30."""
        st, ok = self.st, self.active
        l = self.b.item_topics[item.item_idx].toarray().ravel()
        share = np.asarray(st["topics"][ok] @ l).ravel() / (np.maximum(st["n_all"][ok], 1.0) * max(l.sum(), 1.0))
        return ok[np.lexsort((-st["n30"][ok], -share))[:200]]

    def established(self, p):
        return self.first.get(p, 10 ** 9) <= self.o - 60

    # -- stage B v1 and v2 share the agent draw, as in E5's rerank_b2 (people from the v1 draw, de-duplicated)
    def draw(self):
        jobs = []
        for x in self.short:
            lid = x["id"]
            if lid not in self.items:
                continue
            rng = np.random.default_rng(int(lid))
            top = self.backer_top(self.items[lid])
            pick = list(rng.choice(top, min(self.a.v1_top, len(top)), replace=False)) if len(top) else []
            rnd = [p for p in rng.choice(self.active, 2 * self.a.v1_rand, replace=False) if p not in set(pick)][: self.a.v1_rand]
            jobs += [(lid, int(p), "backer_top") for p in pick] + [(lid, int(p), "random_active") for p in rnd]
        return jobs

    def v1(self, jobs, ndays):
        def page(lid):
            it = self.items[lid]
            return f"{it.title} - {it.summary}\n{str(it.description or '')[:900]}"

        def agent(a):
            lid, p, src = a
            k = self.VR.get(p, 0.0)
            rate = (f"On days they are active, this person upvotes about {k:.1f} of the roughly {ndays} launches of the day (about {100 * k / max(1, ndays):.0f}% of them)."
                    if k else f"This person has upvoted nothing in the last 30 days; today there are roughly {ndays} launches.")
            prompt = PROMPT_V1.format(ups=self.ups(p), cms=self.cms(p), page=page(lid), rate=rate)
            raw = None
            try:
                raw = call(prompt, 300)
                j = json.loads(raw)
            except BudgetExceeded:
                raise
            except Exception:  # noqa: BLE001
                j = {}
            v = str(j.get("vote", "")).lower()
            pp = j.get("p")
            return {"arm": "v1", "launch_id": lid, "person_idx": p, "panel": src, "established": self.established(p),
                    "vote": 1 if v == "yes" else 0 if v == "no" else np.nan,
                    "p": float(pp) / 100 if isinstance(pp, (int, float)) else np.nan,
                    "sentiment": j.get("sentiment") if j.get("sentiment") in ("pos", "neu", "neg") else None,
                    "comment": scrub(j.get("comment", ""))[:200], "prompt": prompt, "raw": raw}
        with cf.ThreadPoolExecutor(self.a.threads) as ex:
            return list(ex.map(agent, jobs))

    def v2(self, jobs):
        ids = [x["id"] for x in self.short if x["id"] in self.items]
        lines = {}
        for lid in ids:
            it = self.items[lid]
            lines[lid] = f"{it.title} - {it.summary} [{', '.join(list(it.tags)[:4])}] {scrub(str(it.description or ''))[:160]}"[:300]
        seen, P = set(), []
        for _, p, s in jobs:
            if p not in seen:
                seen.add(p)
                P.append((p, s))

        def agent(a):
            p, src = a
            seed = int(hashlib.md5((str(p) + self.D).encode()).hexdigest()[:8], 16)
            order = ids[:]
            np.random.default_rng(seed).shuffle(order)
            k = int(min(5, max(1, round(self.VR.get(p, 1.0)))))
            lst = "\n".join(f"{n + 1}. {lines[l]}" for n, l in enumerate(order))
            prompt = PROMPT_V2.format(ups=self.ups(p), cms=self.cms(p), lst=lst, k=k)
            raw, picks = None, None
            try:
                raw = call(prompt, 300)
                j = json.loads(raw)
                picks = [order[int(n) - 1] for n in j.get("picks", []) if 1 <= int(n) <= len(order)][:k]
            except BudgetExceeded:
                raise
            except Exception:  # noqa: BLE001
                pass
            return {"arm": "v2", "person_idx": p, "panel": src, "established": self.established(p), "k": k, "seed": seed,
                    "order": json.dumps(order), "picks": json.dumps(picks) if picks is not None else None, "prompt": prompt, "raw": raw}
        with cf.ThreadPoolExecutor(self.a.threads) as ex:
            return list(ex.map(agent, P))

    def panel(self):
        st = self.st
        pool_ok = np.flatnonzero((st["n60"] >= 1) & (st["n_comments"] >= 3))
        out = []
        for x in self.short:
            lid = x["id"]
            if lid not in self.items:
                continue
            it = self.items[lid]
            l = self.b.item_topics[it.item_idx].toarray().ravel()
            share = np.asarray(st["topics"][pool_ok] @ l).ravel() / (np.maximum(st["n_all"][pool_ok], 1.0) * max(l.sum(), 1.0))
            panel = pool_ok[np.lexsort((-st["n30"][pool_ok], -share))[:30]]
            batch = self.b.batch(self.D, panel)
            fields = _item_fields(Item(-1, lid, "", bench_scrub(it.title), bench_scrub(it.summary or ""),
                                       bench_scrub(it.description or ""), list(it.tags)))
            rows = [(int(p), FT_PROMPT.format(history=batch.render(j, 30, 10), **fields)) for j, p in enumerate(panel)]
            order = list(np.random.default_rng(int(hashlib.md5((lid + self.D).encode()).hexdigest()[:8], 16)).permutation(len(rows)))

            def gen(r):
                p, prompt = r
                p2 = prompt.replace(OLD, NEW) if OLD in prompt else prompt + "\n\nDo not mention your own name, employer or products. Answer in JSON only: {\"comment\": \"...\"}"
                raw = None
                try:
                    raw = call(p2, 300, temperature=0.7)
                    c = str(json.loads(raw).get("comment", "")).strip()
                except BudgetExceeded:
                    raise
                except Exception:  # noqa: BLE001
                    c = ""
                c = re.sub(r"@[A-Za-z0-9_.-]+", "@someone", " ".join(c.split()))
                why = ("empty" if not c else "maker_like" if MAKER.search(c) else "self_named" if SELFNAME.search(c)
                       else "names_own_history_product" if any(n.lower() in c.lower() for n in own_names(prompt)) else None)
                return {"arm": "panel", "launch_id": lid, "person_idx": p, "established": self.established(p),
                        "comment": c, "drop": why, "prompt": p2, "raw": raw}
            kept, pos = 0, 0
            while kept < self.a.panel and pos < len(order):
                need = min(self.a.panel - kept, len(order) - pos)
                batch_rows = [rows[i] for i in order[pos:pos + need]]
                pos += need
                with cf.ThreadPoolExecutor(8) as ex:
                    res = list(ex.map(gen, batch_rows))
                out += res
                kept += sum(1 for r in res if not r["drop"])
        return out


def vader_fn():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    V = SentimentIntensityAnalyzer()
    return lambda t: V.polarity_scores(t)["compound"]


def aggregate(day: Day, A: pd.DataFrame):
    vd = vader_fn()
    rows = []
    v1 = A[A.arm == "v1"]
    v2 = A[A.arm == "v2"]
    v2 = v2[v2.picks.notna()]
    v2p = v2.assign(pl=v2.picks.map(json.loads))
    pn = A[(A.arm == "panel") & A["drop"].isna()] if "drop" in A else A.iloc[:0]
    for x in day.short:
        lid = x["id"]
        r = {"id": lid, "srank": x["srank"], "real": day.truth.get(lid)}
        for tag, est in (("", None), ("_established", True)):
            a = v1[v1.launch_id == lid]
            b = v2p
            c = pn[pn.launch_id == lid]
            if est:
                a, b, c = a[a.established], b[b.established], c[c.established]
            if len(a) and a.vote.notna().any():
                r[f"stageb_v1:yes_share{tag}"] = float(a.vote.mean())
                r[f"stageb_v1:mean_p{tag}"] = float(a.p.mean()) if a.p.notna().any() else None
                s = a.sentiment.value_counts(normalize=True)
                r[f"stageb_v1:sentiment{tag}"] = float(s.get("pos", 0) - s.get("neg", 0))
            if len(b) and lid in day.items:
                r[f"stageb_v2:pick_share{tag}"] = float(np.mean([lid in pl for pl in b.pl]))
            if len(c):
                r[f"person_panel_noblock:sent{tag}"] = float(np.mean([vd(t) for t in c.comment]))
        rows.append(r)
    return rows


def cmd_run(a):
    BUDGET["usd"] = a.budget
    os.makedirs(f"{a.work}/days", exist_ok=True)
    os.makedirs(f"{a.work}/private", exist_ok=True)
    bench = Benchmark(a.bench)
    log = open(f"{a.work}/cost.jsonl", "a")
    for D in a.days.split(","):
        if os.path.exists(f"{a.work}/days/{D}.json"):
            continue
        u0, c0, t0 = usd(), USAGE["calls"], time.time()
        try:
            day = Day(bench, D, a)
            nd = len(day.truth)
            jobs = day.draw()
            A = pd.DataFrame(day.v1(jobs, nd) + day.v2(jobs) + day.panel())
        except BudgetExceeded:
            print(f"{D}: budget reached (${usd():.2f}); stopping", flush=True)
            break
        rows = aggregate(day, A)
        res = {"day": D, "structural_model": day.structural_model, "top_n": TOPN, "n_ranked": len(day.truth),
               "real_top": {N: [k for k, v in day.truth.items() if v <= N] for N in (3, 5)},
               "launches_without_text": [x["id"] for x in day.short if x["id"] not in day.items],
               "agents": {"v1": int((A.arm == "v1").sum()), "v2": int((A.arm == "v2").sum()), "panel": int((A.arm == "panel").sum())},
               "usd": round(usd() - u0, 4), "calls": USAGE["calls"] - c0, "rows": rows,
               "design": vars(a) | {"backer_top": "topic-share stand-in for the CF list", "launch_block": "not available (no-block shadow)"}}
        json.dump(res, open(f"{a.work}/days/{D}.json", "w"), indent=1, default=str)
        A.drop(columns=[]).to_parquet(f"{a.work}/private/{D}.parquet", index=False)
        log.write(json.dumps({"day": D, "usd": res["usd"], "calls": res["calls"], "sec": round(time.time() - t0)}) + "\n")
        log.flush()
        print(f"{D}: ${res['usd']:.3f}, {res['calls']} calls, {time.time() - t0:.0f}s, total ${usd():.2f}", flush=True)
        if a.sync:
            subprocess.run(["gsutil", "-q", "cp", f"{a.work}/days/{D}.json", f"{a.sync}/days/{D}.json"], check=False)
            subprocess.run(["gsutil", "-q", "cp", f"{a.work}/private/{D}.parquet", f"{a.sync}/private/{D}.parquet"], check=False)


def cmd_score(a):
    from scipy.stats import rankdata
    from simharness.resid_nightly import spearman_day, order_with, capture, fit_k, boot
    days = [json.load(open(f)) for f in sorted(glob.glob(f"{a.work}/days/*.json"))]
    names = sorted({k for d in days for r in d["rows"] for k in r if ":" in k})
    out = {"label": "backtest, post-cutoff", "model": MODEL, "top_n": TOPN, "days": [d["day"] for d in days],
           "usd": round(sum(d["usd"] for d in days), 3),
           "notes": ["2026 days only, after gemini-2.5-flash's training cutoff (about Jan 2025)",
                     "survivorship: held people were chosen in Oct-Nov 2026; '_established' lines use agents whose first held upvote is >= 60 days before D",
                     "backer_top drawn by a topic-share stand-in for the CF backer list; person panel without the launch-page block",
                     "agents per launch and panel size reduced from the nightly jobs to fit the budget (see design in each day file)"],
           "lines": {}}
    for nm in names:
        recs = []
        for d in days:
            rows = [{"id": r["id"], "srank": r["srank"], "real": r["real"], "score": r.get(nm)} for r in d["rows"]]
            if any(r["score"] is not None for r in rows):
                recs.append((d, rows))
        rhos = []
        nl = 0
        for d, rows in recs:
            rho, n = spearman_day(rows)
            if rho is not None:
                rhos.append(rho)
                nl += n
        row = {"n_days": len(rhos), "n_launches": nl, "spearman_with_miss": boot(rhos)}
        # the miss regresses to the mean inside the shortlist, so any score that tracks structural rank correlates with
        # it mechanically; these two read whether the score knows anything beyond the structural order
        cs, ps = [], []
        for d, rows in recs:
            R = [r for r in rows if r["score"] is not None and r["real"] is not None]
            if len(R) < 5 or np.std([r["score"] for r in R]) == 0:
                continue
            sc, st, re_ = (rankdata([r[k] for r in R]) for k in ("score", "srank", "real"))
            c = lambda u, v: np.corrcoef(u, v)[0, 1]
            cs.append(c(sc, st))
            ps.append((c(sc, re_) - c(sc, st) * c(re_, st)) / np.sqrt(max(1e-12, (1 - c(sc, st) ** 2) * (1 - c(re_, st) ** 2))))
        row["spearman_with_structural_rank"] = boot(cs)
        row["partial_with_real_rank_given_structural"] = boot(ps)
        for N in (3, 5):
            diffs, ks = [], []
            for d, rows in recs:
                tr = [(r2, {int(k): v for k, v in d2["real_top"].items()}) for d2, r2 in recs if d2["day"] != d["day"]]
                k = fit_k(tr, N)
                top = {int(kk): v for kk, v in d["real_top"].items()}
                diffs.append(capture(order_with(rows, k), top, N) - capture(order_with(rows, 0), top, N))
                ks.append(k)
            row[f"top{N}_capture_change"] = boot(diffs)
            row[f"top{N}_k_by_day"] = ks
        out["lines"][nm] = row
    base = {N: boot([capture([r["id"] for r in sorted(d["rows"], key=lambda r: r["srank"])], {int(k): v for k, v in d["real_top"].items()}, N)
                     for d in days]) for N in (3, 5)}
    out["structural_capture"] = {f"top{N}": base[N] for N in (3, 5)}
    json.dump(out, open(f"{a.work}/score.json", "w"), indent=1)
    if a.leaderboard:
        r = subprocess.run(["gsutil", "-q", "cat", a.leaderboard], capture_output=True)
        lb = json.loads(r.stdout) if r.returncode == 0 and r.stdout else {}
        lb["backtest_post_cutoff"] = out
        p = f"{a.work}/residual_leaderboard.json"
        json.dump(lb, open(p, "w"), indent=1)
        subprocess.run(["gsutil", "-q", "-h", "Content-Type:application/json", "cp", p, a.leaderboard], check=True)
    f = lambda b: "n/a" if b["mean"] is None else (f"{b['mean']:+.3f}" + (f" [{b['lo']:+.3f}, {b['hi']:+.3f}]" if b["lo"] is not None else ""))
    print(f"days {len(days)}  usd {out['usd']}  structural top3 {f(base[3])} top5 {f(base[5])}")
    for nm, r in out["lines"].items():
        print(f"{nm:42s} d {r['n_days']:>2} n {r['n_launches']:>4} rho {f(r['spearman_with_miss'])}  top3 {f(r['top3_capture_change'])}  "
              f"top5 {f(r['top5_capture_change'])}  ~srank {f(r['spearman_with_structural_rank'])}  partial {f(r['partial_with_real_rank_given_structural'])}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--bench", required=True)
    r.add_argument("--days", required=True)
    r.add_argument("--work", required=True)
    r.add_argument("--budget", type=float, default=20.0)
    r.add_argument("--v1-top", type=int, default=12)
    r.add_argument("--v1-rand", type=int, default=4)
    r.add_argument("--panel", type=int, default=6)
    r.add_argument("--threads", type=int, default=16)
    r.add_argument("--sync")
    s = sub.add_parser("score")
    s.add_argument("--work", required=True)
    s.add_argument("--leaderboard")
    a = ap.parse_args(argv)
    cmd_run(a) if a.cmd == "run" else cmd_score(a)


if __name__ == "__main__":
    main()
