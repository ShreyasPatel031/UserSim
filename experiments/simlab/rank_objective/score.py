"""Score rank_objective arms vs arm 3 (PREREG.md). python score.py <preds.parquet> -> result.json here."""
import json, os, sys, numpy as np, pandas as pd
from scipy.stats import spearmanr
HERE = os.path.dirname(os.path.abspath(__file__)); rng = np.random.default_rng(0)
R = pd.read_parquet(sys.argv[1]); R = R[R.dailyRank.notna()].copy(); R["dailyRank"] = R.dailyRank.astype(float)
n = R.groupby("day").size(); R = R[R.day.isin(n[n >= 10].index) & (R.day <= "2026-11-12")]
# (d) 50/50 rank average of arm 3 and (a); ties broken by arm 3
ra = R.groupby("day").arm3.rank(ascending=False); rb = R.groupby("day").a_lambdarank.rank(ascending=False)
R["d_rankavg"] = -(ra + rb) / 2 + R.groupby("day").arm3.rank() * 1e-6
ARMS = ["a_lambdarank", "b_xendcg", "c_pctreg", "d_rankavg"]
G = list(R.groupby("day"))
def hits(col, k): return np.array([len(set(g.nlargest(k, col).id) & set(g[g.dailyRank <= k].id)) / k * 100 for _, g in G])
def sp10(col): return np.array([spearmanr(g[g.dailyRank <= 10][col], -g[g.dailyRank <= 10].dailyRank)[0] for _, g in G])
def ci(v):
    v = v[~np.isnan(v)]; b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()), 3 if abs(v.mean()) < 1.5 else 1), round(float(np.percentile(b, 2.5)), 3 if abs(v.mean()) < 1.5 else 1), round(float(np.percentile(b, 97.5)), 3 if abs(v.mean()) < 1.5 else 1)]
O = {"days": len(G), "window": [R.day.min(), R.day.max()], "launches": int(len(R)), "lines": {}, "paired_vs_arm3": {}, "clears": {}}
base = {k: hits("arm3", k) for k in (3, 5, 10)}; bsp = sp10("arm3")
O["lines"]["arm3"] = {**{f"top{k}": ci(base[k]) for k in (3, 5, 10)}, "spearman_top10": ci(bsp)}
for a in ARMS:
    h = {k: hits(a, k) for k in (3, 5, 10)}; s = sp10(a)
    O["lines"][a] = {**{f"top{k}": ci(h[k]) for k in (3, 5, 10)}, "spearman_top10": ci(s)}
    O["paired_vs_arm3"][a] = {**{f"top{k}": ci(h[k] - base[k]) for k in (3, 5, 10)}, "spearman_top10": ci(s - bsp)}
    p = O["paired_vs_arm3"][a]; O["clears"][a] = bool(any(p[f"top{k}"][1] > 0 for k in (3, 5, 10)) and not any(p[f"top{k}"][2] < 0 for k in (3, 5, 10)))
O["any_clears"] = any(O["clears"].values())
json.dump(O, open(os.path.join(HERE, "result.json"), "w"), indent=1); print(json.dumps(O, indent=1))
