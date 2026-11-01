"""North star: Caught at posting. Each post is scored at its posting moment with only what is known then (title, URL,
submitter, time, its domain / author record, outside signals before posting; no votes or comments of the post).
For each list day D, rank the posts posted on D (UTC) by that score; Caught = |our top 30 of D's posts ∩ D's real
daily top 30| / 30. Holdout Sep 1 - Oct 14; model fit on posts Jul 1 - Aug 31; 95% bootstrap interval over days.
Ceiling: the share of D's real top 30 that was posted on D (re-ups of earlier posts cannot be caught this way).
Extras (labelled as including early votes): the same ranking with each post's score at 15 min / 1 h / 3 h of age.
Input sets (levers) are scored with and without, paired by day.

    python caught.py [lever ...]      # default: the current at-posting inputs; levers: feeds
"""
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

import fine_io
import odds_live as OL
import top100 as H

rng = np.random.default_rng(0)
p = H.stories()
q = p[(p.day >= "2026-07-01") & (p.day <= "2026-10-14")].reset_index(drop=True)
B = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"))
bcols = [x for x in B.columns if x.startswith("b_") and not x.startswith(("b_w30_", "b_w60_"))]
B = B[["post_id", "text_score"] + bcols].drop_duplicates("post_id")
A = pd.read_parquet(os.path.join(H.CACHE, "audience_feats.parquet"))
F2 = pd.read_parquet(os.path.join(H.CACHE, "crowd_v2_feats.parquet"))
Q = q.merge(B, on="post_id", how="left").merge(A, on="post_id", how="left").merge(F2, on="post_id", how="left")
L = OL.lists().sort_values("rank").drop_duplicates(["day", "post_id"])
real = L[L["rank"] <= 30].groupby("day").post_id.apply(set)
POST = ["text_score"] + bcols
KNN = ["knn_lp", "knn_100", "knn_t30", "knn_sim"]
EMB = [f"emb{j}" for j in range(64)]
CROWD = ["aud_sum", "aud_cube", "aud_fans", "scout_sum", "scout_cube", "scout_fans", "fans_any", "top50_sim", "c2_sum", "c2_scout", "c2_top50", "c2_n20"]
Q["y"] = Q.post_id.isin(set(L[L["rank"] <= 30].post_id)).astype(int)     # made any daily top 30 (training label)
fit, te = (Q.day < "2026-09-01").to_numpy(), (Q.day >= "2026-09-01").to_numpy()


def caught(scores):
    """Per day: our top 30 of the day's posts vs the real top 30 of that day's list."""
    T = Q[te].assign(s=scores)
    out = {}
    for d, g in T.groupby("day"):
        if d in real.index:
            out[d] = len(set(g.nlargest(30, "s").post_id) & real[d]) / 30
    return pd.Series(out)


def ci(x):
    b = [rng.choice(x, len(x)).mean() for _ in range(2000)]
    return f"{x.mean():.1%} [{np.percentile(b, 2.5):.1%}, {np.percentile(b, 97.5):.1%}]"


def model(cols, extra=None):
    X = Q[cols] if extra is None else pd.concat([Q[cols], extra], axis=1)
    m = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8,
                           subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0).fit(X[fit], Q.y[fit])
    return m.predict_proba(X[te])[:, 1]


if __name__ == "__main__":
    ceil = pd.Series({d: len(set(Q[te & (Q.day == d).to_numpy()].post_id) & real[d]) / 30 for d in sorted(set(Q.day[te])) if d in real.index})
    print(f"holdout days {len(ceil)}; ceiling (share of the real top 30 posted that day): {ci(ceil.to_numpy())}", flush=True)
    base = caught(model(POST + KNN + EMB + CROWD))
    print(f"Caught at posting (post + domain/author record + similar titles + embedding + crowd): {ci(base.to_numpy())}", flush=True)
    for name, cols in (("post features only", POST), ("+ similar past titles", POST + KNN), ("+ embedding", POST + KNN + EMB)):
        s = caught(model(cols))
        d = (s - base).to_numpy()
        print(f"  {name:28s} {ci(s.to_numpy())}  vs full {d.mean():+.1%}", flush=True)
    # extras including early votes (each post scored at that age; same daily ranking)
    _, qs = fine_io.load()
    q_by_id = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
               for r in qs.itertuples()}
    V = OL.vote_feats(Q, q_by_id, [15, 60, 180])
    for a, label in ((15, "15 min"), (60, "1 h"), (180, "3 h")):
        s = caught(model(POST + KNN + EMB + CROWD, V[a]))
        print(f"Caught at {label} (includes the post's early votes): {ci(s.to_numpy())}", flush=True)
