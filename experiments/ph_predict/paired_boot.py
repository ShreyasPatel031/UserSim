"""Paired bootstrap over days: daily top 3/5/10 of one prediction column in two newsim_eval SAVE=1 runs.
usage: python paired_boot.py results/newsim_preds_A.parquet results/newsim_preds_B.parquet ["+day standing+page"]
Prints B - A with a 95% interval (10,000 day resamples), and the months where B beats A on top 3."""
import sys
import numpy as np, pandas as pd

a, b = pd.read_parquet(sys.argv[1]), pd.read_parquet(sys.argv[2])
col = sys.argv[3] if len(sys.argv) > 3 else "+day standing+page"


def per_day(T, k):
    out = {}
    for d, g in T.groupby("day"):
        if (g.dailyRank <= k).sum() == k:
            out[d] = len(set(g.nlargest(k, col).id) & set(g[g.dailyRank <= k].id)) / k
    return pd.Series(out)


rng = np.random.default_rng(0)
for k in (3, 5, 10):
    A, B = per_day(a, k), per_day(b, k)
    days = A.index.intersection(B.index); diff = (B[days] - A[days]).values
    boot = [diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(10000)]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    line = f"top {k}: A {100 * A[days].mean():.1f}  B {100 * B[days].mean():.1f}  B-A {100 * diff.mean():+.1f} (95% {100 * lo:+.1f} to {100 * hi:+.1f}), {len(days)} days"
    if k == 3:
        m = pd.Series(diff, index=days).groupby(lambda d: d[:7]).mean()
        line += f"; months B>A {int((m > 0).sum())} of {len(m)} ({', '.join(f'{i[5:]} {100 * v:+.1f}' for i, v in m.items())})"
    print(line)
