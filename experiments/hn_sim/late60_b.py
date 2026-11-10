"""1 h live, second step: the late-riser bucket cannot be bought back by reallocating flags (late60_live.py: fixed
off-front share 84 vs 94 on Nov 2-8, two-model merge 94 vs 94). Next bucket, front page by 1 h but ranked below the cut
(44 of 115 misses), where the joint model drops posts with 78-100 points at front rank 2-4. Variants, leave one posting
day out, full-coverage days, flags per day = winners; chosen on Nov 2-8 before reading Nov 9 / Nov 10:
  V0  current joint model (all per-minute 1 h inputs + at-posting odds)
  V5  core inputs only: points, comments, front-page best position / first minute / minutes on it, at-posting odds
  V6  V5 with heavier regularisation (150 trees, min 60 rows per leaf)
  V7  logistic regression on log points, log comments, log front minutes, front best, log odds
  V8  equal-weight rank blend of V0 and the votes score (points + 3 x front page + comments/1000)

    python late60_b.py [feats.parquet]
"""
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

path = sys.argv[1] if len(sys.argv) > 1 else "out/live_minute_feats.parquet"
F = pd.read_parquet(path)
F = F[F.day >= "2026-11-02"].reset_index(drop=True)
y = F.y.to_numpy()
days = sorted(F.day.unique())
ALL = [c for c in F.columns if c.startswith("m60_") and c != "m60_seen"] + ["p_post"]
CORE = ["m60_pts", "m60_cm", "m60_front_best", "m60_front_t", "m60_front_min", "p_post"]
P1 = dict(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=20, verbose=-1, random_state=0)
P2 = dict(n_estimators=150, learning_rate=0.05, num_leaves=7, min_child_samples=60, verbose=-1, random_state=0)
LX = pd.DataFrame({"lp": np.log1p(F.m60_pts), "lc": np.log1p(F.m60_cm), "lf": np.log1p(F.m60_front_min),
                   "fb": np.where(F.m60_front_best < 999, 1 / np.sqrt(F.m60_front_best.clip(lower=1)), 0),
                   "lo": np.log(F.p_post.fillna(0) + 1e-3)})
rk = lambda v: pd.Series(v).rank(pct=True).to_numpy()
votes = F.m60_pts.to_numpy() + 3 * (F.m60_front_best.to_numpy() < 999) + F.m60_cm.to_numpy() * 1e-3
S = {k: np.zeros(len(F)) for k in ("V0", "V5", "V6", "V7")}
for d in days:
    te = (F.day == d).to_numpy()
    tr = ~te
    S["V0"][te] = lgb.LGBMClassifier(**P1).fit(F.loc[tr, ALL], y[tr]).predict_proba(F.loc[te, ALL])[:, 1]
    S["V5"][te] = lgb.LGBMClassifier(**P1).fit(F.loc[tr, CORE], y[tr]).predict_proba(F.loc[te, CORE])[:, 1]
    S["V6"][te] = lgb.LGBMClassifier(**P2).fit(F.loc[tr, CORE], y[tr]).predict_proba(F.loc[te, CORE])[:, 1]
    S["V7"][te] = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000)).fit(LX[tr], y[tr]).predict_proba(LX[te])[:, 1]
S["V8"] = np.zeros(len(F))
for d in days:
    te = (F.day == d).to_numpy()
    S["V8"][te] = 0.5 * rk(S["V0"][te]) + 0.5 * rk(votes[te])


def flags(s):
    out = np.zeros(len(F), bool)
    for d in days:
        te = (F.day == d).to_numpy()
        out[te] = pd.Series(s[te]).rank(ascending=False, method="first").to_numpy() <= y[te].sum()
    return out


dev = (F.day <= "2026-11-08").to_numpy()
w = y == 1
off = (F.m60_front_best >= 999).to_numpy()
FL = {k: flags(v) for k, v in S.items()}
print(f"{'variant':6s} {'Nov 2-8':>12s} {'front-page misses':>17s} " + " ".join(f"{d[5:]:>7s}" for d in days))
for k, fl in FL.items():
    by = " ".join(f"{int((fl & w & (F.day == d).to_numpy()).sum()):>3d}/{int((w & (F.day == d).to_numpy()).sum()):<3d}" for d in days)
    print(f"{k:6s} {int((fl & w & dev).sum()):>4d}/{int((w & dev).sum())} {(fl & w & dev).sum() / (w & dev).sum():5.1%} "
          f"{int((~fl & w & ~off & dev).sum()):>10d}        " + by)
best = max(("V5", "V6", "V7", "V8"), key=lambda k: (FL[k] & w & dev).sum())
print(f"chosen on Nov 2-8: {best}")
