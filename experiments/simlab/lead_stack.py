"""PRE-REGISTERED joint stack of today's weak leads on arm 2 (orchestrator 00:36Z Nov 14). List fixed before any result; no additions.
Leads (as-of-date definitions only; within-day z, counts as log1p):
  L1 c0          distinct non-hunter commenters with createdAt <= 00:00 PT (precom_timing.py)
  L2 asof_any    held team members with >= 1 dated activity before the launch day (team_inc2.py, provenance store 19:58Z)
  L3 fth_top5    first-time hunter (2025 lists + 2026 warehouse) x team's upvotes on top-5 launches in the prior 365 d (first_hunter.py)
  L4 structure   maker/hunter pre-launch comment: log length, multi-author flag, log hours before 00:00 (maker_comment.py; 0 if none)
  L5 founder     founder_story trait 0-2 (gemini-2.5-flash-lite, masked text; 0 if no comment)
  L6 margin      own arm-2 score minus the day's #4 arm-2 score; enters alone AND as interactions z(margin) x each of L1-L5's terms
Model: ONE month-forward ridge (alpha 10) on within-day z, target z(-ln rank): base = z(arm2 both); full = base + all terms above.
Common launches: arm-2 days (Apr-Oct) with thread dumps (<= Oct 24); days with >= 10 such launches. Scored: months after the first.
Report: top 3/5/10 vs arm 2 (base ridge), paired, day bootstrap: all scored days; last half of scored days; drop-one (each of L1..L6 with
its interactions removed); launch-age terciles (scored days in thirds). Rule 5: qualifies only if all-days top-3 interval excludes 0, the
last half keeps the sign, and the newest tercile is not zero.
    python lead_stack.py <scratchpad> <stack dir> <out dir>
"""
import json, os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import Ridge
SP, SD, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True); rng = np.random.default_rng(0)
A = pd.read_parquet(f"{SP}/history_retrain_decomp_preds_arm2.parquet")[["id", "day", "both", "dailyRank"]]; A["id"] = A.id.astype(str)
f1 = pd.read_parquet(f"{SD}/precom.parquet")[["id", "c0"]]; f2 = pd.read_parquet(f"{SD}/team.parquet")[["id", "asof_any"]]; f3 = pd.read_parquet(f"{SD}/fth.parquet")[["id", "fth", "t_top5_365"]]
T = pd.read_parquet(f"{SP}/maker_comment/texts.parquet")[["id", "len_pre", "multi_team", "hrs_before"]]
TR = pd.DataFrame([json.loads(l) for l in open(f"{SP}/maker_comment/traits.jsonl")]).drop_duplicates("id")[["id", "founder_story"]]
for d in (f1, f2, f3, T, TR): d["id"] = d.id.astype(str)
M = A.merge(f1, on="id").merge(f2, on="id", how="left").merge(f3, on="id", how="left").merge(T, on="id", how="left").merge(TR, on="id", how="left")
M = M.fillna({"asof_any": 0, "fth": False, "t_top5_365": 0, "len_pre": 0, "multi_team": 0, "hrs_before": 0, "founder_story": 0})
M["founder_story"] = pd.to_numeric(M.founder_story, errors="coerce").fillna(0); M["fth_top5"] = M.fth.astype(float) * np.log1p(M.t_top5_365)
M = M[M.groupby("day").id.transform("count") >= 10].copy(); M["mon"] = M.day.str[:7]; M["rank"] = M.dailyRank.astype(float)
z = lambda s: (s - s.mean()) / (s.std() or 1); gz = lambda c, f=lambda s: s: M.groupby("day")[c].transform(lambda s: z(f(s)))
M["zb"] = gz("both"); M["y"] = M.groupby("day")["rank"].transform(lambda r: z(-np.log(r)))
M["L1"] = gz("c0", np.log1p); M["L2"] = gz("asof_any", np.log1p); M["L3"] = gz("fth_top5"); M["L4a"] = gz("len_pre", np.log1p); M["L4b"] = gz("multi_team")
M["L4c"] = gz("hrs_before", lambda s: np.log1p(s.clip(lower=0))); M["L5"] = gz("founder_story")
M["mg"] = M.both - M.groupby("day").both.transform(lambda s: s.sort_values(ascending=False).iloc[3] if len(s) > 3 else s.min()); M["L6"] = gz("mg")
G = {"L1": ["L1"], "L2": ["L2"], "L3": ["L3"], "L4": ["L4a", "L4b", "L4c"], "L5": ["L5"]}
for g, cs in G.items():
    for c in cs: M[f"x_{c}"] = M[c] * M["L6"]
TERMS = {g: cs + [f"x_{c}" for c in cs] for g, cs in G.items()}; TERMS["L6"] = ["L6"] + [f"x_{c}" for cs in G.values() for c in cs]
ALL = sorted({t for v in TERMS.values() for t in v}, key=lambda t: (t.startswith("x_"), t))
ARMS = {"arm2": ["zb"], "full": ["zb"] + ALL, **{f"drop {g}": ["zb"] + [t for t in ALL if t not in (TERMS[g] if g != "L6" else TERMS["L6"])] for g in TERMS}}
mons = sorted(M.mon.unique())
for a, X in ARMS.items():
    M["p_" + a] = np.nan
    for m in mons[1:]:
        tr, te = M[M.mon < m], M[M.mon == m]; M.loc[te.index, "p_" + a] = Ridge(alpha=10).fit(tr[X], tr.y).predict(te[X])
S = M[M.p_arm2.notna()]; days = sorted(S.day.unique())
def dm(g, col):
    o = g.sort_values(col, ascending=False).id.tolist(); t = g.sort_values("rank").id.tolist(); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
R = {a: np.array([dm(S[S.day == d], "p_" + a) for d in days]) for a in ARMS}
def ci(D):
    bs = np.array([D[rng.integers(0, len(D), len(D))].mean(0) for _ in range(4000)])
    return [[round(float(D[:, j].mean()), 1), round(float(np.percentile(bs[:, j], 2.5)), 1), round(float(np.percentile(bs[:, j], 97.5)), 1)] for j in range(3)]
half = np.arange(len(days)) >= len(days) // 2; terc = np.array_split(np.arange(len(days)), 3)
res = {"design": __doc__.split("\n    python")[0], "common launches": len(M), "scored days": len(days), "first/last": [days[0], days[-1]], "terms": ALL,
       "arm2 top3/5/10": R["arm2"].mean(0).round(1).tolist(), "full top3/5/10": R["full"].mean(0).round(1).tolist(),
       "full - arm2, all days": ci(R["full"] - R["arm2"]), "full - arm2, last half": ci((R["full"] - R["arm2"])[half]),
       "full - arm2 by age tercile (0 = oldest)": {k: ci((R["full"] - R["arm2"])[ix]) for k, ix in enumerate(terc)},
       "drop-one: (arm - arm2) top3/5/10": {a: ci(R[a] - R["arm2"]) for a in ARMS if a.startswith("drop")}}
d0 = ci(R["full"] - R["arm2"])[0]; lh = ci((R["full"] - R["arm2"])[half])[0]; nt = ci((R["full"] - R["arm2"])[terc[2]])[0]
res["rule 5"] = {"all-days top-3 interval excludes 0": d0[1] > 0, "last half keeps sign": (lh[0] > 0) == (d0[0] > 0), "newest tercile not zero": nt[1] > 0 or nt[2] < 0,
                 "QUALIFIES": bool(d0[1] > 0 and (lh[0] > 0) == (d0[0] > 0) and (nt[1] > 0 or nt[2] < 0))}
json.dump(res, open(os.path.join(OUT, "lead_stack.json"), "w"), indent=1, default=float); print(json.dumps({k: v for k, v in res.items() if k != "design"}, default=float))
