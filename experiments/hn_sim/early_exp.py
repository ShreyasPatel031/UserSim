"""Post-only vs post + early comments (first 30 / 60 min), daily top 10 / 30, test months 2026-05..2026-09
(BigQuery data ends Oct 17). Same classifier as the best post-only variant (made the day's top 30)."""
import lightgbm as lgb
import numpy as np
import pandas as pd

import rank as R
import store as S
import top10 as T

p = T.stories()
p = p[p.day < "2026-10-01"].reset_index(drop=True)
F = T.feats(p)
E = S.read("hn_scores")
E = E[E.kind == "early"].drop_duplicates("post_id").set_index("post_id")
for c in ("c15", "c30", "c60", "u60"):
    F[c] = p.post_id.map(E[c]).fillna(0).to_numpy()
y = np.log1p(p.points.to_numpy())
rk = p.groupby("day").points.rank(ascending=False, method="first").to_numpy()
rng = np.random.default_rng(0)
V = {"post_only": [c for c in F.columns if c not in ("c15", "c30", "c60", "u60")],
     "plus_30min": [c for c in F.columns if c not in ("c60", "u60")],
     "plus_60min": list(F.columns)}
out = []
for m in ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]:
    tr, te = (p.month < m).to_numpy(), (p.month == m).to_numpy()
    oof, txt = T.text_scores(p, y, tr, te)
    res = {"day": p.day[te].to_numpy(), "y": y[te]}
    for name, cols in V.items():
        c = lgb.LGBMClassifier(**{**T.GBM, "scale_pos_weight": 5})
        c.fit(F[tr][cols].assign(text_score=oof), (rk[tr] <= 30).astype(int))
        res[name] = c.predict_proba(F[te][cols].assign(text_score=txt))[:, 1]
    out.append(pd.DataFrame(res))
    print(m, flush=True)
P = pd.concat(out, ignore_index=True)
for name in V:
    print(name, {k: R.boot(T.day_hits(P, name, k, rng)) for k in (10, 30)})
