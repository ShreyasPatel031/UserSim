"""Score walkforward.py output against the month-forward backtest (results/history_retrain_decomp_preds_arm2.parquet: 'both' = arm 2,
'pure' = plain 2026 clean), paired by day, 10,000-draw day bootstrap; cuts: >= 10 ranked (183), all 214, last 90 of the 183.
usage: python3 walkforward_score.py <wf_preds_stepN.parquet> [label]"""
import sys
import numpy as np, pandas as pd
W = pd.read_parquet(sys.argv[1]); W["id"] = W.id.astype(str); lab = sys.argv[2] if len(sys.argv) > 2 else "walk-forward"
A = pd.read_parquet("results/history_retrain_decomp_preds_arm2.parquet"); A["id"] = A.id.astype(str); A = A.dropna(subset=["dailyRank"])
A = A.merge(W[["id", "both", "pure"]].rename(columns={"both": "wf_both", "pure": "wf_pure"}), on="id", how="inner")
for c in ("wf_both", "wf_pure"): A[c] = A.groupby("day")[c].transform(lambda s: s.fillna(s.min() - 1))
hits = lambda o, t: [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
def top(c, days): return np.array([hits(g.sort_values([c, "id"], ascending=[False, True]).id.tolist(), g.sort_values("dailyRank").id.tolist()) for d, g in A[A.day.isin(days)].groupby("day")])
nr = A.groupby("day").size(); D10 = sorted(nr[nr >= 10].index); rng = np.random.default_rng(0)
def ci(x):
    b = np.array([x[rng.integers(0, len(x), len(x))].mean(0) for _ in range(10000)])
    return " / ".join(f"{x[:, k].mean():+.1f} [{np.percentile(b[:, k], 2.5):+.1f}, {np.percentile(b[:, k], 97.5):+.1f}]" for k in range(3))
for cut, days in ((">= 10 ranked", D10), ("all", sorted(A.day.unique())), ("last 90 of >= 10", D10[-90:])):
    mb, mp, wb, wp = top("both", days), top("pure", days), top("wf_both", days), top("wf_pure", days)
    print(f"{cut} ({len(days)} d): month-fwd arm2 {mb.mean(0).round(1).tolist()} clean {mp.mean(0).round(1).tolist()} | {lab} arm2 {wb.mean(0).round(1).tolist()} clean {wp.mean(0).round(1).tolist()}")
    print(f"   {lab} - month-fwd: arm2 {ci(wb - mb)}; clean {ci(wp - mp)}")
    print(f"   arm2 - clean: month-fwd {ci(mb - mp)}; {lab} {ci(wb - wp)}")
