"""How well do the simulation and the launch model do on first-time teams (no maker had an earlier launch in our data,
which starts Jan 2026; the hunter is not counted) vs repeat teams? Atelier's users are mostly new products, so the first-time rows are the ones that matter.
Same out-of-sample predictions as comp_test.py (rolling monthly, Jul-Oct): simulation only (pst_ + tpd_), launch only
(ctrl.py all inputs), both. Within each day, among launches of the same kind:
  pairs     which of two launches gets more votes (random 50%)
  groups3   which of three gets the most (random 33.3%)
  corr      rank correlation of prediction with real votes
usage: python newteam_eval.py -> results/newteam_eval.json"""
import glob, json
import numpy as np, pandas as pd, lightgbm as lgb
from scipy.stats import spearmanr
from newteam_eval_lib import first_time


def load(p):
    return pd.DataFrame.from_dict(json.load(open(f"data/{p}_features.json")), orient="index").rename_axis("id").reset_index()


C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str)
A = C[["id", "day", "dailyRank", "logv", "all"]].merge(load("pst"), on="id").merge(load("tpd"), on="id")
for c in [c for c in A if c.startswith("pst_") and not c.endswith("pmax")]:
    A[c] = np.log1p(A[c])
sc = [c for c in A if c.startswith(("pst_", "tpd_"))]
A["mon"] = A.day.str[:7]
out = []
for m in sorted(A.mon.unique())[1:]:
    tr, te = A[A.mon < m], A[A.mon == m].copy()
    fit = lambda cols: np.mean([lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8, subsample_freq=1,
                                                  colsample_bytree=0.5, random_state=s, verbose=-1, n_jobs=8).fit(tr[cols], tr.logv).predict(te[cols]) for s in range(3)], 0)
    te["simulation only"] = fit(sc); te["both"] = fit(sc + ["all"]); out.append(te)
T = pd.concat(out).rename(columns={"all": "launch only"})
ft = first_time(); T["first_time"] = T.id.map(ft)
P = ["simulation only", "launch only", "both"]; rng = np.random.default_rng(0)
res = {"months_tested": sorted(T.mon.unique()), "first_time_teams_known": int(T.first_time.notna().sum())}
for name, flag in (("first-time teams", True), ("repeat teams", False)):
    S = T[T.first_time == flag]; r = {"launches": len(S)}
    pair, trip, corr = {p: [] for p in P}, {p: [] for p in P}, {p: [] for p in P}
    for _, g in S.groupby("day"):
        g = g.reset_index(drop=True)
        if len(g) >= 2:
            for i in range(len(g)):
                for j in range(i + 1, len(g)):
                    if g.logv[i] != g.logv[j]:
                        for p in P:
                            pair[p].append((g[p][i] > g[p][j]) == (g.logv[i] > g.logv[j]))
        if len(g) >= 3:
            for _ in range(min(20, len(g))):
                k = g.loc[rng.choice(len(g), 3, replace=False)]
                if k.logv.nunique() == 3:
                    for p in P:
                        trip[p].append(k[p].idxmax() == k.logv.idxmax())
        if len(g) >= 5:
            for p in P:
                corr[p].append(spearmanr(g[p], g.logv).correlation)
    for p in P:
        r[p] = {"pairs": round(100 * float(np.mean(pair[p])), 1), "groups3": round(100 * float(np.mean(trip[p])), 1),
                "corr": round(float(np.nanmean(corr[p])), 3)}
    r["n_pairs"] = len(pair[P[0]]); r["n_groups3"] = len(trip[P[0]])
    res[name] = r
json.dump(res, open("results/newteam_eval.json", "w"), indent=1); print(json.dumps(res, indent=1))
