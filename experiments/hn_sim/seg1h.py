"""Checkpoint 1: segmented model at 1 h. Posts already on the front page by 1 h vs posts still only on /new get
separate classifiers (same inputs: rank-only votes, curve, comments, who, history score); their probabilities are
pooled for the global flags. Compared with the single model on the same inputs, paired by day.

    python seg1h.py      # needs caught60_feats.parquet from HIST=1 RANK_ONLY=1 caught1h.py
"""
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import caught as C
import top100 as H

C.Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
F = pd.read_parquet(os.path.join(H.CACHE, "caught60_feats.parquet"))
F = F[[c for c in F.columns if c == "post_id" or not c.startswith(("points", "gain30", "rate", "cv_p", "cv_acc", "mx_gravity", "mx_dead"))]]
X = C.Q[["post_id"] + C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior"]].merge(F, on="post_id", how="left").drop(columns="post_id")
y = C.Q.y.to_numpy()
prm = dict(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8, subsample_freq=1,
           colsample_bytree=0.8, verbose=-1, random_state=0)
single = lgb.LGBMClassifier(**prm).fit(X[C.fit], y[C.fit]).predict_proba(X[C.te])[:, 1]
base = C.caught(single)
print(f"single model at 1 h: {C.ci(base)}", flush=True)
vis = (X.best_rank <= 30).to_numpy()
seg = np.zeros(len(X))
for m in (vis, ~vis):
    mdl = lgb.LGBMClassifier(**prm).fit(X[C.fit & m], y[C.fit & m])
    seg[C.te & m] = mdl.predict_proba(X[C.te & m])[:, 1]
s = C.caught(seg[C.te])
print(f"segmented (front page by 1 h / /new only): {C.ci(s)}  vs single {C.diff(s, base)}", flush=True)
T = C.Q[C.te].assign(s=single, v=vis[C.te])
k = int(T.y.sum())
T["flag"] = T.s.rank(ascending=False, method="first") <= k
for v, g in T.groupby("v"):
    print(f"  {'on front page by 1 h' if v else 'not yet on front page'}: posts {len(g)}, winners {int(g.y.sum())}, "
          f"flagged {int(g.flag.sum())}, winners caught {int((g.flag & (g.y == 1)).sum())}", flush=True)
