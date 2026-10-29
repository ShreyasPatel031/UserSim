import json, numpy as np, pandas as pd
from scipy.stats import spearmanr
P = pd.read_parquet("results/ctrl_preds.parquet"); P["resid"] = P.logv - P.fixed
V = pd.DataFrame.from_dict(json.load(open("data/vs_features.json")), orient="index"); V.index.name = "id"
A = P.merge(V.reset_index(), on="id")
print("launches with a scored video:", len(A))
rng = np.random.default_rng(0)
for c in [c for c in V.columns if A[c].nunique() > 1]:
    x = A[[c, "resid"]].dropna()
    r = spearmanr(x[c], x.resid).correlation
    bs = [spearmanr(*x.sample(len(x), replace=True, random_state=i)[[c, "resid"]].values.T).correlation for i in range(300)]
    print(f"{c:24s} {r:+.3f}  [{np.percentile(bs, 2.5):+.3f}, {np.percentile(bs, 97.5):+.3f}]  n={len(x)}")
