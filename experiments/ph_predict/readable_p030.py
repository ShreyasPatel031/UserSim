"""00:30 switch test (orchestrator 19:10Z Nov 13): readable v2 + the mrep comment inputs vs the published P030 line (pred_rank_mrep = clean +
th_n_pre + distinct commenters + total comments + hunter-only replies, maker_replies.py) on the same 214 days; per-day hits dumped by
maker_replies.py MR_DUMP with MR_BASE = clean (tw_nosite) or b (readable v2 stumps). Paired day bootstrap on all days and the last half.
usage: python readable_p030.py <dump_clean.csv> <dump_b.csv> -> results/readable_p030.md"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
C, B = pd.read_csv(sys.argv[1]), pd.read_csv(sys.argv[2]); rng = np.random.default_rng(0)
V = "+ total + replies (hunter only)"
md = ["# 00:30 switch test: readable v2 + 00:30 comment inputs vs published mrep (214 days, LODO, paired day bootstrap)", "",
      "Both lines: base + th_n_pre + distinct commenters + total comments <= 00:30 + hunter replies <= 00:30 (the frozen mrep inputs); base = clean_nosite (published) or readable v2 stumps (10 inputs; 14 named inputs total, all monotone in the stumps / additive in the ridge).", "",
      "| point | variant | days | published (clean base) t3/t5/t10 | readable base t3/t5/t10 | diff t3 / t5 / t10 (95%) | call |", "|---|---|---|---|---|---|---|"]
for pt in sorted(C.point.unique()):
    for v in (V, "+ total comments"):
        c = C[(C.point == pt) & (C.variant == v)].sort_values("day"); b = B[(B.point == pt) & (B.variant == v)].sort_values("day")
        m = c.merge(b, on="day", suffixes=("_c", "_b")); days = len(m)
        for lab, sl in (("all", slice(None)), ("last half", slice(days // 2, None))):
            mm = m.iloc[sl]; D = np.stack([mm[f"{k}_b"] - mm[f"{k}_c"] for k in ("t3", "t5", "t10")], 1)
            bs = np.array([D[rng.integers(0, len(D), len(D))].mean(0) for _ in range(3000)]); lo, hi = np.percentile(bs, 2.5, 0), np.percentile(bs, 97.5, 0)
            nw = lo[0] <= 0 <= hi[0] and abs(D[:, 0].mean()) <= 1.5
            md.append(f"| {pt} | {v} | {lab} {len(mm)} | {mm.t3_c.mean():.1f} / {mm.t5_c.mean():.1f} / {mm.t10_c.mean():.1f} | {mm.t3_b.mean():.1f} / {mm.t5_b.mean():.1f} / {mm.t10_b.mean():.1f} | " +
                      " / ".join(f"{D[:, k].mean():+.1f} [{lo[k]:+.1f}, {hi[k]:+.1f}]" for k in range(3)) + f" | {'not worse' if nw else ('better' if lo[0] > 0 else 'worse')} |")
open(f"{HERE}/results/readable_p030.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))
