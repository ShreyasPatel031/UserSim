"""Arm 3 (2025 + 2024 + 2023 lists) vs arm 2 (2025 lists, the deployed 00:05 line) on the same 214 days (Apr-Oct 2026), rule 5:
better on the leak-free paired backtest with the 95% interval excluding 0 on the north-star cut (top 3) => deploy.
Inputs: results/history_retrain_decomp_preds_arm2.parquet (arm 2 DECOMP, column both) and results/history_retrain_decomp_preds_arm3.parquet
(ARM3=1 DECOMP=1 DECOMP_TAG=_arm3; columns pure, both). Same ids/days only; paired day bootstrap (3000, seed 0) as h25_stack.py.
usage: python3 arm3_compare.py -> results/arm3_compare.md"""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); R = os.path.join(HERE, "results")


def hits(o, t):
    return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]


def per_day(A, col):
    out = []
    for d, g in A.groupby("day"):
        t = g.sort_values("dailyRank").id.tolist(); o = g.sort_values([col, "id"], ascending=[False, True]).id.tolist()
        out.append(hits(o, t) + [g[col].corr(-g.dailyRank, method="spearman")])
    return np.array(out)


def main():
    a2 = pd.read_parquet(f"{R}/history_retrain_decomp_preds_arm2.parquet"); a3 = pd.read_parquet(f"{R}/history_retrain_decomp_preds_arm3.parquet")
    for X in (a2, a3):
        X["id"] = X.id.astype(str)
    a3 = a3[(a3.day >= "2026-04-01") & (a3.day <= "2026-10-31")]
    A = a2[["id", "day", "dailyRank", "both", "pure"]].rename(columns={"both": "arm2", "pure": "pure2"}).merge(
        a3[["id", "both", "pure"]].rename(columns={"both": "arm3", "pure": "pure3"}), on="id").dropna(subset=["dailyRank", "arm2", "arm3"])
    days = sorted(A.day.unique()); rng = np.random.default_rng(0)
    base = per_day(A, "arm2"); md = [f"# Arm 3 vs arm 2, 00:05 ({len(days)} days {days[0]} - {days[-1]}, {len(A)} launches, paired day bootstrap)", "",
                                     "| line | top 3 | top 5 | top 10 | daily rho | diff vs arm 2 (t3 / t5 / t10 / rho, 95%) |", "|---|---|---|---|---|---|"]
    verdict = None
    for c in ("arm2", "arm3", "pure3"):
        X = per_day(A, c); dP = X - base
        b = np.array([np.nanmean(dP[rng.integers(0, len(dP), len(dP))], 0) for _ in range(3000)])
        lo, hi = np.nanpercentile(b, 2.5, 0), np.nanpercentile(b, 97.5, 0)
        ci = " / ".join(f"{np.nanmean(dP[:, k]):+.{3 if k == 3 else 1}f} [{lo[k]:+.{3 if k == 3 else 1}f}, {hi[k]:+.{3 if k == 3 else 1}f}]" for k in range(4))
        md.append(f"| {c} | {X[:,0].mean():.1f} | {X[:,1].mean():.1f} | {X[:,2].mean():.1f} | {np.nanmean(X[:,3]):.3f} | {'-' if c == 'arm2' else ci} |")
        if c == "arm3":
            verdict = ("DEPLOY arm 3 (rule 5: top 3 interval above 0)" if lo[0] > 0 else
                       "keep arm 2 (rule 5: top 3 interval includes or is below 0)") + f"; top 3 {np.nanmean(dP[:, 0]):+.1f} [{lo[0]:+.1f}, {hi[0]:+.1f}]"
    if len(days) != 214:
        md += ["", f"WARNING: {len(days)} common days, not 214; check that both DECOMP runs covered Apr-Oct 2026."]
    md += ["", "pure3 = the pure 2026 line from the arm-3 run (sanity: should match arm 2's pure within seed noise).", "", f"Rule 5: {verdict}"]
    open(f"{R}/arm3_compare.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
