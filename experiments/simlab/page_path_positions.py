"""Zero-cost re-analysis of the page_path adjudications (orchestrator 13:34Z Nov 12): p@1 / p@2 / p@3 and hit@k vs the constant list,
precision by list position, and p@3 by number of real comments (5-9, 10-19, 20+) with the constant per bin. Both adjudicated runs
(run 1 = page_path.py, run 2 = page_path_draft.py re-adjudication). Only the top 3 of each list were adjudicated, so no p@5.
    python page_path_positions.py <ph-website worktree> <scratchpad> <page_path out dir>
"""
import os, sys, json
WT, SP0, OUTD = sys.argv[1:4]; HERE = os.path.dirname(os.path.abspath(__file__))
PP = open(os.path.join(HERE, "page_path.py")).read(); sys.argv = [sys.argv[0], WT, SP0, OUTD]
exec(PP[:PP.index("async def one(x, sem):")])   # LAUNCH (with comments), cache C; no model calls
def mb(v):
    v = np.array([z for z in v if z is not None and not np.isnan(z)], float)
    if not len(v): return None
    bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()) * 100, 1), round(float(np.percentile(bs, 2.5)) * 100, 1), round(float(np.percentile(bs, 97.5)) * 100, 1), len(v)]
pk = lambda o, n, k: float(np.mean(o[n][:k])) if o.get(n) and len(o[n]) >= k else np.nan
hk = lambda o, n, k: float(any(o[n][:k])) if o.get(n) and len(o[n]) >= k else np.nan
pos = lambda o, n, i: float(o[n][i]) if o.get(n) and len(o[n]) > i else np.nan
res = {"design": __doc__.split("\n    python")[0]}
for run, pref in (("run1", "adj|"), ("run2", "adj2|")):
    R = [(x, C[pref + x["key"]]) for x in LAUNCH if C.get(pref + x["key"])]; rr = {"launches": len(R)}
    for kind in ("RC", "RQ"):
        o_ = {}
        for arm in ("c_ph", "b_raw", "a_read", "const"):
            n = f"{kind}_{arm}"
            o_[arm] = {**{f"p@{k}": mb([pk(o, n, k) for _, o in R]) for k in (1, 2, 3)}, **{f"hit@{k}": mb([hk(o, n, k) for _, o in R]) for k in (1, 2, 3)},
                       "by_position": [mb([pos(o, n, i) for _, o in R])[0] for i in range(3)]}
            if arm != "const":
                o_[f"{arm} - const"] = {f"p@{k}": mb([pk(o, n, k) - pk(o, f"{kind}_const", k) for _, o in R]) for k in (1, 3)}
                o_[f"{arm} position1 - positions2-3 (paired)"] = mb([pos(o, n, 0) - np.nanmean([pos(o, n, 1), pos(o, n, 2)]) for _, o in R])
        nc = np.array([len(x["comments"]) for x, _ in R]); bins = (("5-9", nc < 10), ("10-19", (nc >= 10) & (nc < 20)), ("20+", nc >= 20))
        o_["p@3_by_comments"] = {lab: {arm: mb([pk(o, f"{kind}_{arm}", 3) for (x, o), m in zip(R, msk) if m]) for arm in ("c_ph", "b_raw", "const")} for lab, msk in bins}
        rr["concerns" if kind == "RC" else "questions"] = o_
    res[run] = rr
json.dump(res, open(os.path.join(OUTD, "page_path_positions.json"), "w"), indent=1, default=float)
for run in ("run1", "run2"):
    for kind in ("concerns", "questions"):
        o = res[run][kind]
        for arm in ("c_ph", "b_raw", "a_read", "const"): print(run, kind, arm, "p@1", o[arm]["p@1"], "p@3", o[arm]["p@3"], "hit@1", o[arm]["hit@1"][0], "hit@3", o[arm]["hit@3"][0], "pos", o[arm]["by_position"])
        for arm in ("c_ph", "b_raw", "a_read"): print("   ", arm, "-const", o[f"{arm} - const"], "pos1-pos23", o[f"{arm} position1 - positions2-3 (paired)"])
        print("   by comments", json.dumps(o["p@3_by_comments"]))
