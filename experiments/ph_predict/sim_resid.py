"""Can the simulation fix the launch model's misses? Target = real log votes minus the out-of-sample launch model
(ctrl.py "all"); inputs = simulation outputs only (pst_ person sim with page + taste, tpd_ reach x conversion, psn_
no-page sim). Rolling monthly (train earlier months, test the next, Jul-Oct), 3 seeds. Score = launch model + predicted
miss. Daily top 3/5/10 vs launch model alone, paired over days.
usage: python sim_resid.py -> results/sim_resid.json"""
import json
import numpy as np, pandas as pd, lightgbm as lgb

D = "data"
def load(p):
    return pd.DataFrame.from_dict(json.load(open(f"{D}/{p}_features.json")), orient="index").rename_axis("id").reset_index()
C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str)
A = C[["id", "day", "dailyRank", "logv", "all"]].merge(load("pst"), on="id").merge(load("tpd"), on="id").merge(load("psn"), on="id")
for c in [c for c in A if c.startswith(("pst_", "psn_")) and not c.endswith("pmax")]:
    A[c] = np.log1p(A[c])
cols = [c for c in A if c.startswith(("pst_", "psn_", "tpd_"))]
for c in cols:   # standing within the day too
    A[c + "_r"] = A.groupby("day")[c].rank(pct=True)
cols += [c + "_r" for c in cols]
A["miss"] = A.logv - A["all"]; A["mon"] = A.day.str[:7]
out = []
for m in sorted(A.mon.unique())[1:]:
    tr, te = A[A.mon < m], A[A.mon == m].copy()
    te["pred"] = np.mean([lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=7, min_child_samples=40, subsample=0.8, subsample_freq=1,
                                            colsample_bytree=0.5, reg_lambda=5, random_state=s, verbose=-1, n_jobs=8).fit(tr[cols], tr.miss).predict(te[cols]) for s in range(3)], 0)
    out.append(te)
T = pd.concat(out); T["launch+sim"] = T["all"] + T.pred
hit = lambda g, c, k: len(set(g.nlargest(k, c).id) & set(g[g.dailyRank <= k].id)) / k
res = {"months": sorted(T.mon.unique()), "days": int(T.day.nunique()), "sim_inputs": len(cols),
       "miss_corr": round(float(np.nanmean([np.corrcoef(g.pred, g.miss)[0, 1] for _, g in T.groupby("day") if len(g) >= 8])), 3)}
rng = np.random.default_rng(0)
for k in (3, 5, 10):
    days = [g for _, g in T.groupby("day") if (g.dailyRank <= k).sum() == k]
    a = np.array([hit(g, "all", k) for g in days]); b = np.array([hit(g, "launch+sim", k) for g in days]); d = b - a
    bs = [rng.choice(d, len(d)).mean() for _ in range(2000)]
    res[f"top{k}"] = {"launch": round(100 * a.mean(), 1), "launch+sim": round(100 * b.mean(), 1),
                      "diff_ci95": [round(100 * float(np.percentile(bs, 2.5)), 1), round(100 * float(np.percentile(bs, 97.5)), 1)],
                      "days_better_worse": [int((d > 0).sum()), int((d < 0).sum())]}
json.dump(res, open("results/sim_resid.json", "w"), indent=1); print(json.dumps(res, indent=1))
