import sys, json, numpy as np, pandas as pd
rng = np.random.default_rng(0)
def sc(A, col):
    out = {}
    for d, g in A.groupby("day"):
        t = g.sort_values("dailyRank").id.tolist(); o = g.sort_values([col, "id"], ascending=[False, True]).id.tolist()
        out[d] = [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
    return pd.DataFrame(out, index=["t3", "t5", "t10"]).T.sort_index()
def paired(A, a, b, days=None):
    X, Y = sc(A, a), sc(A, b)
    if days is not None: X, Y = X.loc[days], Y.loc[days]
    D = (Y - X).values; bs = np.array([D[rng.integers(0, len(D), len(D))].mean(0) for _ in range(3000)])
    return {k: [round(D[:, i].mean(), 1), round(np.percentile(bs[:, i], 2.5), 1), round(np.percentile(bs[:, i], 97.5), 1)] for i, k in enumerate(["t3", "t5", "t10"])}
