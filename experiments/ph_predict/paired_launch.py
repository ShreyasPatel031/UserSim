"""Paired by-day comparison of two newsim_eval runs (SAVE=1 SAVE_PATH=...): for every prediction column both runs share,
daily top 3/5/10 hit (launches ranked by the prediction vs the real daily rank), the per-day difference B - A with a
95% bootstrap interval over days, and how many test months B is better. Only days and launches present in both runs.
usage: python paired_launch.py results/newsim_preds_A.parquet results/newsim_preds_B.parquet [out.json]"""
import json, sys
import numpy as np, pandas as pd

A, B = pd.read_parquet(sys.argv[1]), pd.read_parquet(sys.argv[2])
fixed = {"id", "day", "dailyRank", "logv", "first_time", "mon"}
cols = [c for c in A.columns if c in B.columns and c not in fixed and not c.startswith(("nsa_", "tpd_", "pst_"))]
M = A[["id", "day", "dailyRank"] + cols].merge(B[["id"] + cols], on="id", suffixes=("_a", "_b"))
rng = np.random.default_rng(0)


def hits(g, c, k):
    return len(set(g.nlargest(k, c).id) & set(g[g.dailyRank <= k].id)) / k


out = {"a": sys.argv[1], "b": sys.argv[2], "launches": len(M), "days": int(M.day.nunique()),
       "months": sorted(M.day.str[:7].unique()), "columns": {}}
for c in cols:
    r = {}
    for k in (3, 5, 10):
        rows = [(d, hits(g, c + "_a", k), hits(g, c + "_b", k)) for d, g in M.groupby("day") if (g.dailyRank <= k).sum() == k]
        D = pd.DataFrame(rows, columns=["day", "a", "b"]); diff = (D.b - D.a).values
        boot = [diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(5000)]
        mon = D.assign(m=D.day.str[:7]).groupby("m")[["a", "b"]].mean()
        r[f"top{k}"] = {"a": round(100 * D.a.mean(), 1), "b": round(100 * D.b.mean(), 1),
                        "b_minus_a": [round(100 * diff.mean(), 1), round(100 * float(np.percentile(boot, 2.5)), 1), round(100 * float(np.percentile(boot, 97.5)), 1)],
                        "days": len(D), "months_b_better": int((mon.b > mon.a).sum()), "months_tied": int((mon.b == mon.a).sum()), "n_months": len(mon)}
    out["columns"][c] = r
print(json.dumps(out, indent=1))
if len(sys.argv) > 3:
    json.dump(out, open(sys.argv[3], "w"), indent=1)
