"""POINT-1: can a person-built comment make the person's actual point as often as a random real commenter does?

Rows: Task C test + forward rows with a second commenter (benchmark + FORWARD-C-1 overlays): the 150 rows of
CONTENT-LABELS-1 plus 150 new ones. Every arm sees the same LAUNCH block, built only from what was knowable at launch:
name, tagline, description and topics from the 00:05 line-up, plus the maker's first top-level comment when the live
stream holds one written in the launch day's first hour (team ids from the line-up). No other person's comment.

Arms (Gemini 2.5 Flash, temperature 0.7, unless noted):
  A0  the current history prompt (task_c.HISTORY_PROMPT wording) with the LAUNCH block
  A1  + "name one specific thing on this launch's page this person would react to, given what they reacted to before"
  A2  two-stage: (1) from the person's past comments, list the kinds of point they make; (2) write the comment making
      that kind of point about something specific on this page
  A3  Claude Opus 5.5 (Vertex) on the A2 stage-2 prompt, reusing A2's stage-1 point kinds (budget)
  ref another real commenter on the same launch
Scoring: same_point (content_judge, 3 runs, majority; the third run only where the first two disagree), person match
(own_vs_other) and length ratio from task_c.

  python -m simharness.run_point1 STAGE --bench B --forward-root F --stream-dir SD --lineup-dir LD --out O [...]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import json
import os
import pickle
import re
import subprocess
import threading

import numpy as np
import pandas as pd

from simharness.bench import _day_bounds_utc, scrub

_lk = threading.Lock()

LAUNCH = """Name: {title}
Tagline: {summary}
Description: {description}
Topics: {tags}
Maker's launch comment: {maker}"""

A0 = """You write the comment one real Product Hunt member leaves on a launch.

THIS MEMBER'S HISTORY (everything known before today):
{history}

TODAY'S LAUNCH:
{launch}

This member did comment on this launch today. Write that comment as they would: their usual length, tone, focus and
kind of question or praise, as their past comments show. Plain text, no hashtags, no quotation marks around it.
Reply with JSON only: {{"comment": "<the comment>"}}"""

A1 = """You write the comment one real Product Hunt member leaves on a launch.

THIS MEMBER'S HISTORY (everything known before today):
{history}

TODAY'S LAUNCH (the launch page):
{launch}

This member did comment on this launch today. First decide which ONE specific thing on this launch's page (a feature,
a claim, a limit, the pricing, a detail in the maker's comment) this person would react to, given what they reacted to
in their past comments. Then write their comment about that one thing, as they would write it: their usual length,
tone, and kind of question or praise. No generic congratulations unless that is all they ever write.
Reply with JSON only: {{"reacts_to": "<the specific thing>", "comment": "<the comment>"}}"""

A2_STAGE1 = """Below is one Product Hunt member's history: what they upvoted and the comments they wrote on earlier launches.
List the KINDS of point this member makes in their comments (for example: asks about pricing, compares to a tool they
use, asks how a specific feature works, tests an edge case, praises the design, asks about integrations, shares their
own use case, generic congratulations). Most frequent first, at most 5, each with how often it appears (often / sometimes / rarely).
Reply with JSON only: {{"point_kinds": [{{"kind": "...", "how_often": "..."}}]}}

HISTORY:
{history}"""

A2_STAGE2 = """You write the comment one real Product Hunt member leaves on a launch.

THIS MEMBER'S HISTORY (everything known before today):
{history}

THE KINDS OF POINT THIS MEMBER MAKES (from their past comments, most frequent first):
{kinds}

TODAY'S LAUNCH (the launch page):
{launch}

This member did comment on this launch today. Write their comment: make the kind of point they most often make,
applied to something specific on this launch's page (a feature, a claim, a limit, the pricing, a detail in the
maker's comment). Use their usual length and tone. No generic congratulations unless that is all they ever write.
Reply with JSON only: {{"comment": "<the comment>"}}"""


def sync(paths, dest):
    if dest and paths:
        subprocess.run(["gsutil", "-q", "-m", "cp", *paths, dest.rstrip("/") + "/"], check=False)


def _bench(a):
    from simharness.bench import Benchmark
    from simharness import task_c as tc
    dirs = sorted(d for d in glob.glob(os.path.join(a.forward_root, "20*")) if os.path.exists(f"{d}/comments.parquet"))
    b = Benchmark(a.bench, overlays=dirs)
    T = tc.TaskC(b)
    T.tau = 0.7497
    return b, T


def launch_pages(b, days, stream_dir, lineup_dir) -> dict:
    """item_idx -> launch block text and provenance; maker comment from the live stream (team ids from the line-up)."""
    out = {}
    iid = {str(i): int(k) for i, k in zip(b.items["item_id"], b.items["item_idx"])}
    for d in days:
        lf = os.path.join(lineup_dir, f"{d}.json")
        if not os.path.exists(lf):
            continue
        posts = json.load(open(lf))
        team = {str(p["id"]): {str(m.get("id")) for m in (p.get("makers") or [])} | {str((p.get("user") or {}).get("id"))}
                for p in posts}
        start, _ = _day_bounds_utc(d, b.cfg.day_tz)
        maker = {}
        sf = os.path.join(stream_dir, f"{d}.jsonl")
        if os.path.exists(sf):
            for line in open(sf):
                if not line.strip():
                    continue
                x = json.loads(line)
                if x.get("parent_id") or str(x.get("commenter_user_id")) not in team.get(str(x.get("launch_id")), set()):
                    continue
                ts = pd.Timestamp(x.get("created_at"))
                if ts.tzinfo is None:
                    ts = ts.tz_localize("UTC")
                if ts >= start + pd.Timedelta(hours=1):
                    continue
                lid = str(x["launch_id"])
                if lid not in maker or ts < maker[lid][0]:
                    maker[lid] = (ts, x.get("body") or "")
        for p in posts:
            k = iid.get(str(p["id"]))
            if k is None:
                continue
            tags = [e["node"]["name"] for e in ((p.get("topics") or {}).get("edges") or []) if e.get("node")]
            mk = maker.get(str(p["id"]))
            mtext = scrub(" ".join(re.sub(r"<[^>]+>", " ", mk[1]).split()))[:900] if mk else "(none)"
            out[k] = {"launch": LAUNCH.format(title=scrub(str(p.get("name") or "")), summary=scrub(str(p.get("tagline") or "")),
                                              description=scrub(" ".join(str(p.get("description") or "").split()))[:900] or "(none)",
                                              tags=", ".join(tags[:6]) or "(none)", maker=mtext),
                      "has_maker_comment": bool(mk)}
    return out


# ------------------------------------------------------------------------------------------------ rows
def stage_rows(a):
    b, T = _bench(a)
    old = pd.read_parquet(a.cl1_pairs)[["person_idx", "item_idx"]].drop_duplicates()
    parts = []
    for split in ("test", "forward"):
        r = T.rows(split)
        parts.append(r[r["same_item_other"].notna() & r["own_past_comment"].notna()].assign(split=split))
    R = pd.concat(parts, ignore_index=True)
    key = set(zip(old.person_idx, old.item_idx))
    R["in_cl1"] = [(int(p), int(i)) in key for p, i in zip(R.person_idx, R.item_idx)]
    new = R[~R["in_cl1"]].sample(150, random_state=21)
    S = pd.concat([R[R["in_cl1"]], new], ignore_index=True)
    pages = launch_pages(b, sorted(S["day"].unique()), a.stream_dir, a.lineup_dir)
    S = S[S["item_idx"].isin(pages)].reset_index(drop=True)
    S["launch_block"] = S["item_idx"].map(lambda k: pages[k]["launch"])
    S["has_maker_comment"] = S["item_idx"].map(lambda k: pages[k]["has_maker_comment"])
    S["history"] = [b.batch(r.day, np.array([r.person_idx])).render(0, 30, 10) for r in S.itertuples()]
    # leak checks
    leak = {"rows": int(len(S)), "rows_from_cl1": int(S["in_cl1"].sum()), "with_maker_comment": int(S["has_maker_comment"].sum())}
    leak["history_lines_on_or_after_day"] = int(sum(sum(1 for m in re.finditer(r"^- (\d{4}-\d{2}-\d{2}): ", h, re.M) if m.group(1) >= d)
                                                    for h, d in zip(S["history"], S["day"])))
    leak["real_comment_in_launch_block"] = int(sum(str(t)[:60] in lb for t, lb in zip(S["text"], S["launch_block"])))
    leak["other_commenter_text_in_launch_block"] = int(sum(str(t)[:60] in lb for t, lb in zip(S["same_item_other"], S["launch_block"])))
    S.to_parquet(f"{a.out}/rows.parquet")
    json.dump(leak, open(f"{a.out}/rows_info.json", "w"), indent=1)
    print(json.dumps(leak))
    sync([f"{a.out}/rows.parquet", f"{a.out}/rows_info.json"], a.sync)


# ------------------------------------------------------------------------------------------------ generate
def _gem(prompt, budget_box):
    from simharness.run_what_panel4 import gemini
    return gemini(prompt, 600, 0.7)


def stage_gen(a):
    from simharness.models.llm import _host, _post
    from simharness.run_what_panel4 import USAGE, usd
    S = pd.read_parquet(f"{a.out}/rows.parquet")
    cp = f"{a.out}/gen_cache.pkl"
    cache = pickle.load(open(cp, "rb")) if os.path.exists(cp) else {}
    opus = {"in": 0, "out": 0}

    def parse(t, key="comment"):
        m = re.search(r"\{.*\}", t or "", re.S)
        try:
            return json.loads(m.group(0)) if m else {}
        except ValueError:
            return {}

    def get(key, fn):
        if key not in cache:
            v = fn()
            with _lk:
                cache[key] = v
        return cache[key]

    def opus_call(prompt):
        url = f"https://{_host('global')}/v1/projects/{a.project}/locations/global/publishers/anthropic/models/claude-opus-5-5:rawPredict"
        d = _post(url, {"anthropic_version": "vertex-2023-10-16", "max_tokens": 3000, "output_config": {"effort": "low"},
                        "messages": [{"role": "user", "content": prompt}]}, timeout=180)
        u = d.get("usage", {})
        with _lk:
            opus["in"] += u.get("input_tokens", 0); opus["out"] += u.get("output_tokens", 0)
        return "".join(c.get("text", "") for c in d.get("content", []) if c.get("type") == "text")

    opus_usd = lambda: opus["in"] * 4 / 1e6 + opus["out"] * 20 / 1e6  # noqa: E731

    def one(r):
        k = (int(r.person_idx), int(r.item_idx))
        out = {}
        out["A0"] = str(parse(get(("A0",) + k, lambda: _gem(A0.format(history=r.history, launch=r.launch_block), None))).get("comment", ""))
        p1 = parse(get(("A1",) + k, lambda: _gem(A1.format(history=r.history, launch=r.launch_block), None)))
        out["A1"], out["A1_reacts_to"] = str(p1.get("comment", "")), str(p1.get("reacts_to", ""))
        kinds = parse(get(("A2s1",) + k, lambda: _gem(A2_STAGE1.format(history=r.history), None))).get("point_kinds") or []
        ktxt = "\n".join(f"- {x.get('kind', '')} ({x.get('how_often', '')})" for x in kinds if isinstance(x, dict)) or "- (no past comments)"
        out["A2_kinds"] = ktxt
        p2 = A2_STAGE2.format(history=r.history, kinds=ktxt, launch=r.launch_block)
        out["A2"] = str(parse(get(("A2",) + k, lambda: _gem(p2, None))).get("comment", ""))
        out["_p2"] = p2
        return out

    with cf.ThreadPoolExecutor(10) as ex:
        res = list(ex.map(one, list(S.itertuples())))
    pickle.dump(cache, open(cp, "wb"))
    flash_usd = usd()
    print("flash usd", flash_usd, flush=True)
    # A3 (Opus) on as many rows as the budget allows, CL1 rows first
    a3_rows = [i for i in range(len(S)) if S["in_cl1"].iloc[i]] + [i for i in range(len(S)) if not S["in_cl1"].iloc[i]]
    a3_rows = a3_rows[: a.a3_rows]

    def a3(i):
        k = ("A3", int(S["person_idx"].iloc[i]), int(S["item_idx"].iloc[i]))
        if opus_usd() > a.a3_cap and k not in cache:
            return i, None
        return i, str(parse(get(k, lambda: opus_call(res[i]["_p2"]))).get("comment", ""))

    with cf.ThreadPoolExecutor(6) as ex:
        a3res = dict(ex.map(a3, a3_rows))
    pickle.dump(cache, open(cp, "wb"))
    G = S[["day", "person_idx", "item_idx", "split", "in_cl1"]].copy()
    for arm in ("A0", "A1", "A2"):
        G[arm] = [x[arm] for x in res]
    G["A1_reacts_to"] = [x["A1_reacts_to"] for x in res]
    G["A2_kinds"] = [x["A2_kinds"] for x in res]
    G["A3"] = [a3res.get(i) for i in range(len(S))]
    G.to_parquet(f"{a.out}/generations.parquet")
    info = {"flash_usd": flash_usd, "opus_usd": round(opus_usd(), 4), "opus_tokens": opus, "a3_rows": int(G["A3"].notna().sum()),
            "empty": {arm: int((G[arm].fillna("") == "").sum()) for arm in ("A0", "A1", "A2", "A3")}}
    json.dump(info, open(f"{a.out}/gen_info.json", "w"), indent=1)
    print(json.dumps(info))
    sync([f"{a.out}/generations.parquet", f"{a.out}/gen_info.json", cp], a.sync)


# ------------------------------------------------------------------------------------------------ judge + score
def stage_score(a):
    from simharness.content_judge import ContentJudge
    from simharness import task_c as tc
    b, T = _bench(a)
    S = pd.read_parquet(f"{a.out}/rows.parquet")
    G = pd.read_parquet(f"{a.out}/generations.parquet")
    assert (S.person_idx.to_numpy() == G.person_idx.to_numpy()).all()
    arms = {"A0": G["A0"], "A1": G["A1"], "A2": G["A2"], "A3": G["A3"], "ref_other_commenter": S["same_item_other"]}
    pairs = []
    it = b.items.set_index("item_idx")
    for arm, col in arms.items():
        for i, t in enumerate(col):
            if isinstance(t, str) and t.strip():
                pairs.append({"arm": arm, "row": i, "launch": f"{it.loc[S.item_idx.iloc[i], 'title']} — {it.loc[S.item_idx.iloc[i], 'summary']}",
                              "real": scrub(" ".join(str(S.text.iloc[i]).split()))[:500], "cand": scrub(" ".join(t.split()))[:500]})
    P = pd.DataFrame(pairs)
    P["pair_id"] = range(len(P))
    j = ContentJudge(a.project, runs=1, cap_usd=a.judge_cap)
    cp = f"{a.out}/judge_cache.pkl"
    cache = pickle.load(open(cp, "rb")) if os.path.exists(cp) else {}
    labs = []
    for run in range(3):
        todo = P
        if run == 2:   # the third run can only change the majority where the first two disagree
            g = pd.concat(labs).groupby("pair_id")["same_point"].agg(["sum", "size"])
            todo = P[P["pair_id"].isin(g[(g["size"] < 2) | (g["sum"] == 1)].index)]
        order = np.random.default_rng(1000 + run).permutation(len(todo))
        batches = [todo.iloc[order[k:k + j.batch]] for k in range(0, len(order), j.batch)]

        def go(rows, run=run):
            key = (run, tuple(sorted(rows["pair_id"].tolist())))
            if key not in cache:
                got = j._batch(rows)
                with _lk:
                    cache[key] = got
            return cache[key]

        with cf.ThreadPoolExecutor(6) as ex:
            got = list(ex.map(go, batches))
        pickle.dump(cache, open(cp, "wb"))
        labs.append(pd.DataFrame([{"pair_id": pid, "run": run, "same_point": sp, "point": pt}
                                  for gg in got for pid, (sp, pt) in gg.items()]))
        print("judge run", run, "pairs", len(todo), "usd so far", round(j.usd, 3), flush=True)
    L = pd.concat(labs, ignore_index=True)
    L.to_parquet(f"{a.out}/judge_runs.parquet")
    maj = L.groupby("pair_id")["same_point"].agg(lambda s: int(s.sum() * 2 > len(s)) if len(s) >= 2 else int(s.iloc[0]))
    pts = L.groupby("pair_id")["point"].agg(lambda s: next((x for x in s if x), ""))
    P["same_point"] = P["pair_id"].map(maj).fillna(0).astype(int)
    P["point"] = P["pair_id"].map(pts)
    P.to_parquet(f"{a.out}/pairs_labelled.parquet")
    # per row x arm table with person match and length
    rows = []
    for arm, col in arms.items():
        texts = [t if isinstance(t, str) and t.strip() else None for t in col]
        sc = T.score(S, texts)
        sp = P[P.arm == arm].set_index("row")["same_point"]
        gp = P[P.arm == arm].set_index("row")["point"].fillna("").str.lower().str.contains("congrat|generic|enthusias")
        for i in range(len(S)):
            if texts[i] is None:
                continue
            rows.append({"arm": arm, "row": i, "day": S.day.iloc[i], "in_cl1": bool(S.in_cl1.iloc[i]),
                         "same_point": int(sp.get(i, 0)), "generic_hit": bool(sp.get(i, 0) and gp.get(i, False)),
                         "own_vs_other": sc["own_vs_other"].iloc[i], "len_ratio": sc["len_ratio"].iloc[i]})
    Rr = pd.DataFrame(rows)
    Rr.to_parquet(f"{a.out}/row_scores.parquet")
    rng = np.random.default_rng(0)

    def boot(df, f):
        days = df["day"].unique()
        idx = {d: np.flatnonzero(df["day"].to_numpy() == d) for d in days}
        pt = f(df)
        bs = [f(df.iloc[np.concatenate([idx[d] for d in rng.choice(days, len(days))])]) for _ in range(3000)]
        lo, hi = np.nanpercentile(bs, [2.5, 97.5])
        return [round(100 * pt, 1), round(100 * lo, 1), round(100 * hi, 1)]

    def paired(x, y, metric, subset=None):
        X = Rr[Rr.arm == x].set_index("row"); Y = Rr[Rr.arm == y].set_index("row")
        ix = X.index.intersection(Y.index)
        if subset is not None:
            ix = ix.intersection(subset)
        df = pd.DataFrame({"day": X.loc[ix, "day"], "d": X.loc[ix, metric].astype(float) - Y.loc[ix, metric].astype(float)}).dropna()
        return boot(df, lambda z: z["d"].mean()) + [int(len(df))]

    res = {"rows": int(len(S)), "days": int(S.day.nunique()), "note": "[value %, day-bootstrap 2.5, 97.5] (+ n for paired)",
           "arms": {}, "paired": {}, "judge_usd": round(j.usd, 3), "gen": json.load(open(f"{a.out}/gen_info.json"))}
    for arm in arms:
        X = Rr[Rr.arm == arm]
        hits = X[X.same_point == 1]
        res["arms"][arm] = {"n": int(len(X)), "same_point": boot(X, lambda z: z["same_point"].mean()),
                            "generic_share_of_hits": round(float(hits["generic_hit"].mean()), 3) if len(hits) else None,
                            "person_match_own_vs_other": boot(X.dropna(subset=["own_vs_other"]), lambda z: z["own_vs_other"].mean()),
                            "length_ratio_median": round(float(X["len_ratio"].median()), 2)}
    a3_rows = set(Rr[Rr.arm == "A3"]["row"])
    for x, y in [("A1", "A0"), ("A2", "A0"), ("A3", "A0"), ("A2", "A1"), ("A3", "A2"), ("A0", "ref_other_commenter"),
                 ("A1", "ref_other_commenter"), ("A2", "ref_other_commenter"), ("A3", "ref_other_commenter")]:
        res["paired"][f"{x} - {y}"] = {m: paired(x, y, m) for m in ("same_point", "own_vs_other")}
    res["paired_on_A3_rows"] = {f"{x} - A0": {m: paired(x, "A0", m, subset=pd.Index(sorted(a3_rows))) for m in ("same_point", "own_vs_other")}
                                for x in ("A1", "A2", "A3")}
    json.dump(res, open(f"{a.out}/point1_results.json", "w"), indent=1, default=float)
    print(json.dumps(res["arms"], indent=0))
    for k, v in res["paired"].items():
        print(k, v)
    print(res["paired_on_A3_rows"], "judge usd", res["judge_usd"])
    sync([f"{a.out}/point1_results.json", f"{a.out}/row_scores.parquet", f"{a.out}/pairs_labelled.parquet", f"{a.out}/judge_runs.parquet"], a.sync)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["rows", "gen", "score"])
    ap.add_argument("--bench", required=True); ap.add_argument("--forward-root", required=True)
    ap.add_argument("--stream-dir", default=""); ap.add_argument("--lineup-dir", default="")
    ap.add_argument("--cl1-pairs", default=""); ap.add_argument("--out", required=True); ap.add_argument("--sync", default="")
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "project-amer-scs-sandbox"))
    ap.add_argument("--a3-rows", type=int, default=150); ap.add_argument("--a3-cap", type=float, default=1.6)
    ap.add_argument("--judge-cap", type=float, default=3.2)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    globals()[f"stage_{a.stage}"](a)


if __name__ == "__main__":
    main()
