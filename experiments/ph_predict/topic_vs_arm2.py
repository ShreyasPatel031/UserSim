"""Paired score: arm 2 + extra inputs (JOINT both_th) vs arm 2 (decomp 'both'). Cuts: days with >= 10 ranked launches (the weekly/E5 day
rule), all 214 days, and the last 90 days of the >= 10 set. Top 3/5/10 hits vs dailyRank; 10,000-draw day bootstrap.
usage: python topic_vs_arm2.py <joint parquet> [label]"""
import sys
import numpy as np, pandas as pd
J = pd.read_parquet(sys.argv[1]); J["id"] = J.id.astype(str)
A = pd.read_parquet("results/history_retrain_decomp_preds_arm2.parquet"); A["id"] = A.id.astype(str)
A = A.dropna(subset=["dailyRank", "both"]).merge(J[["id", "both_th"]], on="id", how="left")
A["both_th"] = A.groupby("day").both_th.transform(lambda s: s.fillna(s.min() - 1))
hits = lambda o, t: [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
nr = A.groupby("day").size(); D10 = sorted(nr[nr >= 10].index)
def top(c, days): return np.array([hits(g.sort_values([c, "id"], ascending=[False, True]).id.tolist(), g.sort_values("dailyRank").id.tolist()) for d, g in A[A.day.isin(days)].groupby("day")])
rng = np.random.default_rng(0); lab = sys.argv[2] if len(sys.argv) > 2 else "joint"
for cut, days in ((">=10 ranked", D10), ("all 214", sorted(A.day.unique())), ("last 90 of >=10", D10[-90:])):
    B, N = top("both", days), top("both_th", days); d = N - B
    b = np.array([d[rng.integers(0, len(d), len(d))].mean(0) for _ in range(10000)])
    print(f"{cut} ({len(d)} days): arm 2 {B.mean(0).round(1).tolist()}  {lab} {N.mean(0).round(1).tolist()}  diff " +
          " / ".join(f"{d[:, k].mean():+.1f} [{np.percentile(b[:, k], 2.5):+.1f}, {np.percentile(b[:, k], 97.5):+.1f}]" for k in range(3)))
