"""Objective test for the daily top 10: regression on points vs a top-10 / top-30 classifier vs a per-day ranker.
Features computed once (top10.feats); test months 2026-05..2026-10, each trained on everything before it."""
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

import rank as R
import top10 as T

p = T.stories()
p = p[p.created_at_i < pd.Timestamp.now(tz="UTC").timestamp() - 3 * 86400].reset_index(drop=True)
F = T.feats(p)
y = np.log1p(p.points.to_numpy())
rk = p.groupby("day").points.rank(ascending=False, method="first").to_numpy()
rng = np.random.default_rng(0)
out = []
for m in ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]:
    tr, te = (p.month < m).to_numpy(), (p.month == m).to_numpy()
    oof, txt = T.text_scores(p, y, tr, te)
    Xtr, Xte = F[tr].assign(text_score=oof), F[te].assign(text_score=txt)
    res = {"day": p.day[te].to_numpy(), "y": y[te]}
    res["reg"] = lgb.LGBMRegressor(**T.GBM).fit(Xtr, y[tr]).predict(Xte)
    for k in (10, 30):
        c = lgb.LGBMClassifier(**{**T.GBM, "scale_pos_weight": 5}).fit(Xtr, (rk[tr] <= k).astype(int))
        res[f"clf{k}"] = c.predict_proba(Xte)[:, 1]
    d = p.day[tr].to_numpy()
    grp = np.diff(np.flatnonzero(np.r_[True, d[1:] != d[:-1], True]))
    lab = np.clip(31 - rk[tr], 0, 30).astype(int)       # graded relevance: top 30 by rank
    r = lgb.LGBMRanker(**{**T.GBM, "n_estimators": 300}, label_gain=list(range(31)))
    res["rank"] = r.fit(Xtr, lab, group=grp).predict(Xte)
    out.append(pd.DataFrame(res))
    print(m, flush=True)
P = pd.concat(out, ignore_index=True)
for col in ("reg", "clf10", "clf30", "rank"):
    print(col, {k: R.boot(T.day_hits(P, col, k, rng)) for k in (10, 30)})
