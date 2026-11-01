"""Competition on /new at posting time (no votes, nothing after the post): for each Jul 1 - Oct 14 post, the posts made
in the 15 / 30 / 60 min before it, and how strong they look at posting (their content prior from audience.py: mean log
points of the 30 nearest past titles; their title text score), plus where the post itself ranks among them.
Volume over the previous hour / day is already in the post features (b_hour_n, b_day_n).
Evaluated as crowd_v2.py: at-posting classifier, train posts Jul-Aug, test Sep 1 - Oct 14, paired-by-day difference
vs the best inputs so far (post + past titles + embedding + crowd v1 + crowd v2).

    python competition.py
"""
import json
import os

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

import top100 as H

rng = np.random.default_rng(0)
p = H.stories()
p = p[(p.day >= "2026-06-30") & (p.day <= "2026-10-14")].sort_values("created_at_i").reset_index(drop=True)
A = pd.read_parquet(os.path.join(H.CACHE, "audience_feats.parquet"))
B = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"))
bcols = [x for x in B.columns if x.startswith("b_") and not x.startswith(("b_w30_", "b_w60_"))]
B = B[["post_id", "text_score"] + bcols].drop_duplicates("post_id")
F2 = pd.read_parquet(os.path.join(H.CACHE, "crowd_v2_feats.parquet"))
p = p.merge(A[["post_id", "knn_lp", "knn_100"]], on="post_id", how="left").merge(B[["post_id", "text_score"]], on="post_id", how="left")
t = p.created_at_i.to_numpy()
kl = p.knn_lp.fillna(p.knn_lp.median()).to_numpy()
ts = p.text_score.fillna(p.text_score.median()).to_numpy()
ckl, cts = np.r_[0, np.cumsum(kl)], np.r_[0, np.cumsum(ts)]
feat = {}
for m in (15, 30, 60):
    lo = np.searchsorted(t, t - m * 60, side="left")
    hi = np.arange(len(t))                                     # posts strictly before this one
    n = hi - lo
    feat[f"comp{m}_n"] = n
    feat[f"comp{m}_knn_mean"] = np.where(n > 0, (ckl[hi] - ckl[lo]) / np.maximum(n, 1), np.nan)
    feat[f"comp{m}_text_mean"] = np.where(n > 0, (cts[hi] - cts[lo]) / np.maximum(n, 1), np.nan)
lo = np.searchsorted(t, t - 1800, side="left")
feat["comp30_knn_max"] = [kl[a:b].max() if b > a else np.nan for a, b in zip(lo, range(len(t)))]
feat["comp30_beats_share"] = [(kl[a:b] < kl[b]).mean() if b > a else np.nan for a, b in zip(lo, range(len(t)))]
Cf = pd.DataFrame(feat)
Cf["post_id"] = p.post_id.to_numpy()
COMP = [c for c in Cf.columns if c != "post_id"]

q = p[p.day >= "2026-07-01"][["post_id", "day"]]
Q = q.merge(B, on="post_id", how="left").merge(A, on="post_id", how="left").merge(F2, on="post_id", how="left").merge(Cf, on="post_id", how="left")
L = pd.read_json(os.path.join(H.CACHE, "frontday.jsonl"), lines=True, dtype={"day": str})
Q["list_rank"] = Q.post_id.map(L.groupby("post_id")["rank"].min()).fillna(999)
tr, te = (Q.day < "2026-09-01").to_numpy(), (Q.day >= "2026-09-01").to_numpy()
POST = ["text_score"] + bcols
KNN = ["knn_lp", "knn_100", "knn_t30", "knn_sim"]
EMB = [f"emb{j}" for j in range(64)]
AUD = ["aud_sum", "aud_cube", "aud_fans", "scout_sum", "scout_cube", "scout_fans", "fans_any", "top50_sim"]
C2 = ["c2_sum", "c2_scout", "c2_top50", "c2_n20"]
BEST = POST + KNN + EMB + AUD + C2
SETS = {"best so far (post + past titles + embedding + crowd v1 + v2)": BEST, "+ /new competition": BEST + COMP}
per_day = {}
for top in (30, 10):
    y = (Q.list_rank <= top).to_numpy()
    for name, cols in SETS.items():
        m = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8,
                               subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0).fit(Q.loc[tr, cols], y[tr])
        s = m.predict_proba(Q.loc[te, cols])[:, 1]
        T = Q[te].assign(s=s, y=y[te])
        cap = T.groupby("day").apply(lambda g: g.nlargest(top, "s").y.sum() / max(g.y.sum(), 1))
        cap100 = T.groupby("day").apply(lambda g: g.nlargest(100, "s").y.sum() / max(g.y.sum(), 1))
        per_day[(top, name)] = cap
        print(json.dumps({"target": f"top {top}", "inputs": name, "AUC": round(roc_auc_score(y[te], s), 3),
                          "avg_precision": round(average_precision_score(y[te], s), 3),
                          f"winners_in_top{top}": round(cap.mean(), 3), "winners_in_top100": round(cap100.mean(), 3)}), flush=True)
    names = list(SETS)
    d = (per_day[(top, names[1])] - per_day[(top, names[0])]).to_numpy()
    boot = [rng.choice(d, len(d)).mean() for _ in range(2000)]
    print(f"  top {top}: + competition vs best so far, winners caught per day: {d.mean():+.3f} "
          f"[{np.percentile(boot, 2.5):+.3f}, {np.percentile(boot, 97.5):+.3f}]", flush=True)
Cf.to_parquet(os.path.join(H.CACHE, "competition_feats.parquet"), index=False)
