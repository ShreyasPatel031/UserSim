"""Per-day confidence for the published 00:05 top 3 (orchestrator 21:06Z Nov 13; observability for the website). Base = arm 2 ('both',
month-fold walk-forward, 214 days Apr-Oct = the deployed model's backtest). Per pick k in 1..3: P(pick finishes in the official top 3),
logistic on: pick position, its score margin over the #4 pick, the #3-#4 margin, the #1-#2 margin, log field size. Fit month-forward
(train on earlier months only; April is train-only). Day confidence = expected picks right (sum of the 3 probabilities).
Reported: calibration by probability decile, Brier vs a position-only baseline, and accuracy on confident vs unconfident days
(split by tercile of day confidence). usage: python top3_confidence.py [preds parquet] [col] -> results/top3_confidence.md + frozen fit"""
import json, os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
HERE = os.path.dirname(os.path.abspath(__file__))
F_ = ["pos2", "pos3", "m_k4", "m_34", "m_12", "lnn"]


def frame(A, col):
    R = []
    for d, g in A.groupby("day"):
        g = g.sort_values([col, "id"], ascending=[False, True]); s = g[col].values; t3 = set(g.sort_values("dailyRank").id.iloc[:3])
        for k in range(3):
            R.append(dict(day=d, mon=d[:7], k=k + 1, id=g.id.iloc[k], y=float(g.id.iloc[k] in t3), pos2=float(k == 1), pos3=float(k == 2),
                          m_k4=s[k] - s[3], m_34=s[2] - s[3], m_12=s[0] - s[1], lnn=np.log(len(g))))
    return pd.DataFrame(R)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else f"{HERE}/results/history_retrain_decomp_preds_arm2.parquet"; col = sys.argv[2] if len(sys.argv) > 2 else "both"
    A = pd.read_parquet(src); A["id"] = A.id.astype(str); A = A.dropna(subset=["dailyRank", col]); A = A[A.groupby("day").id.transform("size") >= 4]
    X = frame(A, col); out = []
    for m in sorted(X.mon.unique())[1:]:
        tr, te = X[X.mon < m], X[X.mon == m]
        full = LogisticRegression(C=1.0, max_iter=1000).fit(tr[F_], tr.y); base = LogisticRegression(max_iter=1000).fit(tr[["pos2", "pos3"]], tr.y)
        out.append(te.assign(p=full.predict_proba(te[F_])[:, 1], p0=base.predict_proba(te[["pos2", "pos3"]])[:, 1]))
    P = pd.concat(out); nd = P.day.nunique()
    brier = lambda p: float(((P[p] - P.y) ** 2).mean())
    md = [f"# How sure are we today: confidence for the published 00:05 top 3 (arm 2, {nd} scored days May-Oct, month-forward)", "",
          f"Pick-level: Brier {brier('p'):.4f} with margins + field size vs {brier('p0'):.4f} position only (lower is better); base rate {P.y.mean():.3f}.", "",
          "## Calibration (pick level, probability deciles)", "", "| predicted range | picks | mean predicted | actually right |", "|---|---|---|---|"]
    P["bin"] = pd.qcut(P.p, 10, duplicates="drop")
    for b, g in P.groupby("bin", observed=True):
        md.append(f"| {b.left:.2f}-{b.right:.2f} | {len(g)} | {g.p.mean():.3f} | {g.y.mean():.3f} |")
    D = P.groupby("day").agg(exp=("p", "sum"), right=("y", "sum"), m34=("m_34", "first"), n=("lnn", "first")).reset_index()
    D["tier"] = pd.qcut(D.exp.rank(method="first"), 3, labels=["low", "mid", "high"])
    md += ["", "## Day level: expected vs actual picks right (of 3), by tercile of day confidence", "",
           "| tier | days | expected right (mean) | actual right (mean) | top-3 accuracy | all 3 right | 0-1 right |", "|---|---|---|---|---|---|---|"]
    for t, g in D.groupby("tier", observed=True):
        md.append(f"| {t} | {len(g)} | {g.exp.mean():.2f} | {g.right.mean():.2f} | {g.right.mean() / 3 * 100:.1f}% | {(g.right == 3).mean() * 100:.0f}% | {(g.right <= 1).mean() * 100:.0f}% |")
    rng = np.random.default_rng(0); hi, lo = D[D.tier == "high"].right.values / 3 * 100, D[D.tier == "low"].right.values / 3 * 100
    bs = [rng.choice(hi, len(hi)).mean() - rng.choice(lo, len(lo)).mean() for _ in range(4000)]
    md.append(f"\nHigh minus low tier top-3 accuracy: {hi.mean() - lo.mean():+.1f} pts [{np.percentile(bs, 2.5):+.1f}, {np.percentile(bs, 97.5):+.1f}].")
    pk = P.groupby("k").agg(pred=("p", "mean"), right=("y", "mean"))
    md += ["", "By pick position: " + "; ".join(f"#{k} predicted {r.pred:.2f}, right {r.right:.2f}" for k, r in pk.iterrows())]
    full = LogisticRegression(C=1.0, max_iter=1000).fit(X[F_], X.y)
    fz = f"{HERE}/results/frozen/top3_confidence_arm2_20261113.json"
    if not os.path.exists(fz) and len(sys.argv) <= 1:
        json.dump({"frozen_at": pd.Timestamp.now(tz="UTC").isoformat(), "base": "arm 2 00:05 score (pred_arm2)", "features": F_,
                   "note": "per pick k (sorted by score): pos2/pos3 one-hot, m_k4 = score_k - score_4, m_34, m_12, lnn = log launches that day",
                   "coef": dict(zip(F_, map(float, full.coef_[0]))), "intercept": float(full.intercept_[0]), "days": int(X.day.nunique())}, open(fz, "w"), indent=1)
        md.append(f"\nFrozen fit (all {X.day.nunique()} days) -> {os.path.relpath(fz, HERE)} for a live shadow file.")
    md.append("Coefficients (full fit): " + ", ".join(f"{f} {c:+.2f}" for f, c in zip(F_, full.coef_[0])))
    open(f"{HERE}/results/top3_confidence.md", "w").write("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main()
