import json, sys, numpy as np, pandas as pd
SP = sys.argv[1]; rng = np.random.default_rng(0)
R = pd.read_parquet(f"{SP}/nc/nc_oos.parquet"); R = R[R.dailyRank.notna()].copy(); n = R.groupby("day").size(); R = R[R.day.isin(n[n >= 10].index)]
R["new"] = R.hist_hunter_n.fillna(0) == 0
def hits(col, k): return np.array([len(set(g.nlargest(k, col).id) & set(g[g.dailyRank <= k].id)) / k * 100 for _, g in R.groupby("day")])
def nrec(col):
    o = []
    for _, g in R.groupby("day"):
        t = g[(g.dailyRank <= 10) & g.new]
        if len(t): o.append(len(set(g.nlargest(10, col).id) & set(t.id)) / len(t) * 100)
    return np.array(o)
def ci(v, s=False):
    b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]; f = "+.1f" if s else ".1f"; return f"{v.mean():{f}} [{np.percentile(b, 2.5):{f}}, {np.percentile(b, 97.5):{f}}]"
O = {"days": int(R.day.nunique()), "window": [R.day.min(), R.day.max()], "lines": {}, "paired": {}}
for k in (3, 5, 10):
    a, b = hits("pred3", k), hits("pred4", k); O["lines"][f"top{k}"] = {"arm 3": ci(a), "arm 3 + hunter history": ci(b)}; O["paired"][f"top{k}"] = ci(b - a, True)
    if k == 10: d10 = b - a
    if k == 3: d3 = (b - a).mean()
a, b = nrec("pred3"), nrec("pred4"); O["newcomer_top10_recall"] = {"days": len(a), "arm 3": ci(a), "with hunter history": ci(b), "paired": ci(b - a, True)}
lo = np.percentile([d10[rng.integers(0, len(d10), len(d10))].mean() for _ in range(2000)], 2.5); O["adopt_by_prereg"] = bool(lo > 0 and d3 >= -1)
H = pd.read_parquet(f"{SP}/nc/hfeats.parquet"); R = R.merge(H, on="id", how="left")
nw = R[R.new]; O["newcomer_launches"] = int(len(nw)); O["newcomer_hunter_in_store"] = round(float(nw.H4_in_store.mean()), 3)
O["newcomer_with_any_dated_prior_hunt_or_launch"] = round(float(((nw.H1_hunts > 0) | (nw.H2_launches > 0)).mean()), 3)
O["newcomer_top10_rate_by_prior_history"] = nw.assign(h=((nw.H1_hunts > 0) | (nw.H2_launches > 0)).map({True: "has earlier hunt or launch", False: "none"})).groupby("h").apply(lambda g: {"n": len(g), "top10_%": round(float((g.dailyRank <= 10).mean() * 100), 1)}).to_dict()
O["newcomer_top10_rate_by_in_store"] = nw.groupby("H4_in_store").apply(lambda g: {"n": len(g), "top10_%": round(float((g.dailyRank <= 10).mean() * 100), 1)}).to_dict()
json.dump(O, open(f"{SP}/nc/result.json", "w"), indent=1, default=str); print(json.dumps(O, indent=1, default=str))
