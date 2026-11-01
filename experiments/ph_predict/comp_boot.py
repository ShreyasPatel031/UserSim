"""Day-clustered paired bootstrap for winner of 3 (comp_test.py groups): B - A on the same groups (matched by window
and launch ids), resampling days (a group belongs to its anchor launch's day) so overlapping groups from one day move
together. 10,000 resamples, 95% interval.
usage: python comp_boot.py results/comp_groups_A.parquet results/comp_groups_B.parquet [column, default "simulation only"]
       (B's column may differ: add  colA,colB)"""
import sys
import numpy as np, pandas as pd

A, B = pd.read_parquet(sys.argv[1]), pd.read_parquet(sys.argv[2])
ca, cb = (sys.argv[3].split(",") + [None])[:2] if len(sys.argv) > 3 else ("simulation only", None)
cb = cb or ca
rng = np.random.default_rng(0)
for win in ("day", "week", "mon"):
    J = A[A.win == win][["key", "day", ca]].merge(B[B.win == win][["key", cb]].rename(columns={cb: "b"}), on="key")
    J["d"] = J.b.astype(float) - J[ca].astype(float)
    by = J.groupby("day").d.agg(["sum", "size"]); s, n = by["sum"].values, by["size"].values
    bs = []
    for _ in range(10000):
        k = rng.integers(0, len(s), len(s)); bs.append(s[k].sum() / n[k].sum())
    lo, hi = np.percentile(bs, [2.5, 97.5])
    print(f"{win:5s} groups {len(J)} days {len(s)}: A {100 * J[ca].mean():.1f} B {100 * J.b.mean():.1f} B-A {100 * J.d.mean():+.1f} (95% {100 * lo:+.1f} to {100 * hi:+.1f})")
