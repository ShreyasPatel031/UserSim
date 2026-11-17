"""Pre-registered fix (PREREG_fix.md, aa36f2a9): month-forward offset for launches whose hunter has no record."""
import json, sys, numpy as np, pandas as pd
SP = sys.argv[1]; OUT = f"{SP}/mna/out"; rng = np.random.default_rng(0)
R = pd.read_parquet(f"{OUT}/arm3_oos_contrib.parquet"); R = R[R.dailyRank.notna()].copy(); n = R.groupby("day").size(); R = R[R.day.isin(n[n >= 10].index)]
R["y"] = np.log1p(R.votes.astype(float)); R["res"] = R.y - R.pred3; R["nr"] = R.hist_hunter_n.fillna(0) == 0; R["m"] = R.day.str[:7]
R["y"] = R.y - R.groupby("day").y.transform("mean"); R["res"] = R.y - (R.pred3 - R.groupby("day").pred3.transform("mean"))   # day-centred, as the ranking only uses within-day order
delta = {}
for m in sorted(R.m.unique()):
    E = R[R.m < m]
    if not len(E): continue
    delta[m] = float(E[E.nr].res.mean() - E[~E.nr].res.mean())
R = R[R.m.isin(delta)]; R["fix"] = R.pred3 + R.m.map(delta) * R.nr
def hits(col, k): return np.array([len(set(g.nlargest(k, col).id) & set(g[g.dailyRank <= k].id)) / k * 100 for _, g in R.groupby("day")])
def ci(v, s=False):
    b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]; f = "+.1f" if s else ".1f"; return f"{v.mean():{f}} [{np.percentile(b, 2.5):{f}}, {np.percentile(b, 97.5):{f}}]"
O = {"days": int(R.day.nunique()), "window": [R.day.min(), R.day.max()], "delta_by_month": {k: round(v, 3) for k, v in delta.items()}, "lines": {}, "paired": {}}
for k in (3, 5, 10):
    a, b = hits("pred3", k), hits("fix", k); O["lines"][f"top{k}"] = {"arm 3": ci(a), "fix": ci(b)}; O["paired"][f"top{k}"] = ci(b - a, True)
    if k == 10: d10 = b - a
    if k == 3: d3 = (b - a).mean()
lo = np.percentile([d10[rng.integers(0, len(d10), len(d10))].mean() for _ in range(2000)], 2.5)
O["adopt"] = bool(lo > 0 and d3 >= -1); oct_ = R[R.day <= "2026-10-31"]
O["no_record_share_in_top10_pred_vs_real"] = {"arm 3": round(float(R[R.groupby("day").pred3.rank(ascending=False) <= 10].nr.mean()), 3), "fix": round(float(R[R.groupby("day").fix.rank(ascending=False) <= 10].nr.mean()), 3), "real": round(float(R[R.dailyRank <= 10].nr.mean()), 3)}
json.dump(O, open(f"{OUT}/fix_result.json", "w"), indent=1); print(json.dumps(O, indent=1))
