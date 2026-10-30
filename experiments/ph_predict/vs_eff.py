"""Video facts vs over-performance at fixed reach, launches with a watched video only (NaN-safe), Mar-Oct."""
import json, numpy as np, pandas as pd
from scipy.stats import spearmanr
P = pd.read_parquet("results/ctrl_preds.parquet"); P["id"] = P.id.astype(str); P["resid"] = P.logv - P.fixed
V = pd.DataFrame.from_dict(json.load(open("data/vs_features.json")), orient="index").rename_axis("id").reset_index()
A = P.merge(V, on="id"); rng = np.random.default_rng(0)
print("launches with a watched video:", len(A))
for c in [c for c in V.columns if c.startswith("vs_")]:
    per = [spearmanr(g[c], g.resid).correlation for _, g in A.dropna(subset=[c]).groupby("day") if len(g) >= 5 and g[c].nunique() > 1]
    per = np.array([x for x in per if x == x])
    if len(per) < 20:
        continue
    bs = [rng.choice(per, len(per)).mean() for _ in range(1000)]
    lo, hi = np.percentile(bs, [2.5, 97.5])
    print(f"{c:26s} {per.mean():+.3f} [{lo:+.3f}, {hi:+.3f}] days {len(per)}{'  *' if lo > 0 or hi < 0 else ''}")
