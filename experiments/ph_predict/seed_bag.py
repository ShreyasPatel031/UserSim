"""Seed bagging for arm 2 (orchestrator 19:36Z Nov 13): single seed vs 5-seed mean (and 10-seed mean when
results/history_retrain_decomp_seeds_s10_arm2.parquet exists), variant 'both' (arm 2), same 214 days, paired day bootstrap,
all days and last 107. usage: python seed_bag.py -> results/seed_bag.md"""
import os
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
def hits(o, t): return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
A = pd.read_parquet(f"{HERE}/results/history_retrain_decomp_preds_arm2.parquet")[["id", "day", "dailyRank"]]; A["id"] = A.id.astype(str); A = A.dropna(subset=["dailyRank"])
S5 = pd.read_parquet(f"{HERE}/results/history_retrain_decomp_seeds_arm2.parquet"); S5 = S5[S5.variant == "both"]; S5["id"] = S5.id.astype(str)
lines = {"1 seed (seed 0)": S5[S5.seed == 0].groupby("id").pred.mean(), "5-seed mean (deployed)": S5.groupby("id").pred.mean()}
p10 = f"{HERE}/results/history_retrain_decomp_seeds_s10_arm2.parquet"
if os.path.exists(p10):
    S10 = pd.read_parquet(p10); S10 = S10[S10.variant == "both"]; S10["id"] = S10.id.astype(str); lines["10-seed mean"] = S10.groupby("id").pred.mean()
per = {}
for nm, s in lines.items():
    X = A.assign(p=A.id.map(s)).dropna(subset=["p"])
    per[nm] = pd.DataFrame([[d] + hits(g.sort_values(["p", "id"], ascending=[False, True]).id.tolist(), g.sort_values("dailyRank").id.tolist()) for d, g in X.groupby("day")], columns=["day", "t3", "t5", "t10"]).set_index("day")
ref = per["5-seed mean (deployed)"]; rng = np.random.default_rng(0); days = sorted(ref.index)
md = ["# Seed bagging, arm 2 (214 days Apr-Oct, month walk-forward)", "", "| line | days | top 3 / 5 / 10 | diff vs 5-seed mean, all days (95%) | diff, last 107 (95%) |", "|---|---|---|---|---|"]
for nm, X in per.items():
    j = X.join(ref, rsuffix="_r", how="inner"); out = []
    for sl in (slice(None), slice(len(j) // 2, None)):
        jj = j.sort_index().iloc[sl]; D = np.stack([jj[k] - jj[k + "_r"] for k in ("t3", "t5", "t10")], 1)
        b = np.array([D[rng.integers(0, len(D), len(D))].mean(0) for _ in range(3000)]); lo, hi = np.percentile(b, 2.5, 0), np.percentile(b, 97.5, 0)
        out.append(" / ".join(f"{D[:, k].mean():+.1f} [{lo[k]:+.1f}, {hi[k]:+.1f}]" for k in range(3)))
    md.append(f"| {nm} | {len(j)} | {X.t3.mean():.1f} / {X.t5.mean():.1f} / {X.t10.mean():.1f} | {out[0]} | {out[1]} |")
open(f"{HERE}/results/seed_bag.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))
