"""Arm 2 learning curve over history length (orchestrator 19:44Z Nov 13). Reads results/history_retrain_decomp_preds_lc{N}_arm2.parquet
(N most recent training days before each test month) and the full-history arm 2 (history_retrain_decomp_preds_arm2.parquet, 'both');
same 214 days. Paired day bootstrap vs N = all; least-squares fit of top 3 on log(training days) with a bootstrap interval for the
extrapolation to 1,000 and 1,400 days. Season split: _seasame / _seaother (2025 rows from the test month's calendar month only / other
months only). usage: python learning_curve.py -> results/learning_curve.md"""
import os
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); R = f"{HERE}/results"
def hits(o, t): return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
def per_day(A, col="both"):
    A = A.dropna(subset=["dailyRank", col]); A = A[(A.day >= "2026-04-01") & (A.day <= "2026-10-31")]
    return pd.DataFrame([[d] + hits(g.sort_values([col, "id"], ascending=[False, True]).id.tolist(), g.sort_values("dailyRank").id.tolist()) + [g[col].corr(-g.dailyRank, method="spearman")] for d, g in A.groupby("day")], columns=["day", "t3", "t5", "t10", "rho"]).set_index("day")
full = pd.read_parquet(f"{R}/history_retrain_decomp_preds_arm2.parquet"); ref = per_day(full)
# training days per test month for N = all: 2026 days before the month + 365 days of 2025 (approx, from the build)
rng = np.random.default_rng(0); md = ["# Arm 2 learning curve over history length (214 days Apr-Oct 2026, month walk-forward, 5 seeds)", "",
     "| training days (most recent N) | top 3 / 5 / 10 | rho | diff vs all history, t3 / t5 / t10 (95%) |", "|---|---|---|---|"]
pts = []
for N in (150, 250, 350, 450):
    p = f"{R}/history_retrain_decomp_preds_lc{N}_arm2.parquet"
    if not os.path.exists(p): continue
    X = per_day(pd.read_parquet(p)); j = X.join(ref, rsuffix="_r", how="inner"); D = np.stack([j[k] - j[k + "_r"] for k in ("t3", "t5", "t10")], 1)
    b = np.array([D[rng.integers(0, len(D), len(D))].mean(0) for _ in range(3000)]); lo, hi = np.percentile(b, 2.5, 0), np.percentile(b, 97.5, 0)
    md.append(f"| {N} | {X.t3.mean():.1f} / {X.t5.mean():.1f} / {X.t10.mean():.1f} | {X.rho.mean():.3f} | " + " / ".join(f"{D[:, k].mean():+.1f} [{lo[k]:+.1f}, {hi[k]:+.1f}]" for k in range(3)) + " |")
    pts.append((N, X))
NALL = int(os.environ.get("N_ALL", "655")); md.append(f"| all (~{NALL}) | {ref.t3.mean():.1f} / {ref.t5.mean():.1f} / {ref.t10.mean():.1f} | {ref.rho.mean():.3f} | - |")
pts.append((NALL, ref))
if len(pts) >= 3:
    xs = np.log([n for n, _ in pts]); days = sorted(set.intersection(*[set(X.index) for _, X in pts]))
    Y = np.array([[X.loc[d, "t3"] for d in days] for _, X in pts])   # rows: N, cols: days
    def fit(Yd):
        y = Yd.mean(1); a, c = np.polyfit(xs, y, 1); return a, c
    a, c = fit(Y); boot = []
    for _ in range(3000):
        idx = rng.integers(0, len(days), len(days)); a_, c_ = fit(Y[:, idx]); boot.append([a_ * np.log(t) + c_ for t in (1000, 1400)] + [a_])
    boot = np.array(boot); pr = [a * np.log(t) + c for t in (1000, 1400)]
    md += ["", f"Fit top 3 = {a:+.2f} x ln(training days) {c:+.1f} (per doubling {a * np.log(2):+.2f} points; slope 95% [{np.percentile(boot[:, 2], 2.5) * np.log(2):+.2f}, {np.percentile(boot[:, 2], 97.5) * np.log(2):+.2f}] per doubling).",
           f"Extrapolated top 3 at 1,000 days (adding 2024): {pr[0]:.1f} [{np.percentile(boot[:, 0], 2.5):.1f}, {np.percentile(boot[:, 0], 97.5):.1f}]; at 1,400 days (adding 2023): {pr[1]:.1f} [{np.percentile(boot[:, 1], 2.5):.1f}, {np.percentile(boot[:, 1], 97.5):.1f}] (day-bootstrap interval of the fitted line only; extrapolation assumes older years help like recent ones, which the season split below tests)."]
md += ["", "## 2025 rows: same calendar month as the test month vs other months (2026 rows kept in both)", "", "| 2025 rows kept | top 3 / 5 / 10 | diff vs all 2025 rows (95%) |", "|---|---|---|"]
for s in ("same", "other"):
    p = f"{R}/history_retrain_decomp_preds_sea{s}_arm2.parquet"
    if not os.path.exists(p): continue
    X = per_day(pd.read_parquet(p)); j = X.join(ref, rsuffix="_r", how="inner"); D = np.stack([j[k] - j[k + "_r"] for k in ("t3", "t5", "t10")], 1)
    b = np.array([D[rng.integers(0, len(D), len(D))].mean(0) for _ in range(3000)]); lo, hi = np.percentile(b, 2.5, 0), np.percentile(b, 97.5, 0)
    md.append(f"| {'same month only (~1/12 of 2025)' if s == 'same' else 'other months only (~11/12)'} | {X.t3.mean():.1f} / {X.t5.mean():.1f} / {X.t10.mean():.1f} | " + " / ".join(f"{D[:, k].mean():+.1f} [{lo[k]:+.1f}, {hi[k]:+.1f}]" for k in range(3)) + " |")
open(f"{R}/learning_curve.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))
