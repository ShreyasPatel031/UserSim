"""Paired score of a JOINT=1 run's both_th (arm 2 + extra inputs inside, 2025 rows missing them) vs deployed arm 2 (decomp 'both'),
same 214 days Apr-Oct, all days and last 107. usage: python joint_vs_arm2.py results/history_retrain_joint_arm2<TAG>.parquet [label]"""
import sys
import numpy as np, pandas as pd
J = pd.read_parquet(sys.argv[1]); J["id"] = J.id.astype(str)
A = pd.read_parquet("results/history_retrain_decomp_preds_arm2.parquet"); A["id"] = A.id.astype(str)
A = A.dropna(subset=["dailyRank", "both"]).merge(J[["id", "both_th"]], on="id", how="left")
A["both_th"] = A.groupby("day").both_th.transform(lambda s: s.fillna(s.min() - 1))
hits = lambda o, t: [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
def top(c): return np.array([hits(g.sort_values([c, "id"], ascending=[False, True]).id.tolist(), g.sort_values("dailyRank").id.tolist()) for _, g in A.groupby("day")])
B, N = top("both"), top("both_th"); rng = np.random.default_rng(0)
print(f"{len(B)} days; arm 2 {B.mean(0).round(1).tolist()}; {sys.argv[2] if len(sys.argv) > 2 else 'joint'} {N.mean(0).round(1).tolist()}")
for lab, sl in (("all", slice(None)), ("last 107", slice(-107, None))):
    d = N[sl] - B[sl]; b = np.array([d[rng.integers(0, len(d), len(d))].mean(0) for _ in range(4000)])
    print(lab, " / ".join(f"{d[:, k].mean():+.1f} [{np.percentile(b[:, k], 2.5):+.1f}, {np.percentile(b[:, k], 97.5):+.1f}]" for k in range(3)))
