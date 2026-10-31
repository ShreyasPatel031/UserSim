"""Audience simulation at posting time: given a new post (title + domain, posting hour), who on HN would like it and
who is around to see it. No votes used.

People: everyone with 10+ comments in the 18 months before SNAP. Per person, from their comments before SNAP only:
  taste      unit mean of the title embeddings (embed.py) of the stories they commented on, recency-weighted (half-life 180 d)
  rate       comments per day over the last 180 days
  hour[h]    share of their comments made in UTC hour h (last 180 days), smoothed
  scout      share of their comments made within 60 min of the story's posting (people who browse /new)
Per post at its posting hour h, over people p, with sim = cos(taste_p, post) and w_p = rate_p * hour_p[h]:
  aud_sum = sum w_p * relu(sim)        aud_cube = sum w_p * relu(sim)^3        aud_fans = sum w_p * [sim > 0.6]
  scout_sum / scout_cube / scout_fans  the same with w_p * scout_p
  fans_any = people with sim > 0.6 regardless of hour; top50_sim = mean sim of the 50 closest people
Content prior (no people): among stories posted before SNAP, the 30 nearest titles: mean log points, share with 100+
points, share on a daily top 30 (lists from 2025-01).
Then: at-posting classifier (top 30 / top 10 of the daily list) on posts Jul 1 - Aug 31 (train) and Sep 1 - Oct 14
(test): post features alone (per_post.py baseline) vs + content prior vs + embedding (PCA 64) vs + audience.
-> <cache>/audience_feats.parquet; scores printed.

    python audience.py [snap=2026-06-30]
"""
import json
import os
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

import top100 as H

SNAP = sys.argv[1] if len(sys.argv) > 1 else "2026-06-30"
T_SNAP = pd.Timestamp(SNAP, tz="UTC").timestamp() + 86400
OUT = os.path.join(H.CACHE, "audience_feats.parquet")

p = H.stories()
E = pd.read_parquet(os.path.join(H.CACHE, "title_emb.parquet"))
emb = np.stack(E.emb.to_numpy()).astype(np.float32)
emb /= np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9
ei = pd.Series(np.arange(len(E)), index=E.post_id)
print("embeddings", emb.shape, flush=True)

# ---- people -----------------------------------------------------------------------------------------------------
c = pd.read_parquet(os.path.join(H.CACHE, "bq_comments.parquet"), columns=["person", "story_id", "created_at_i"])
c = c[(c.created_at_i < T_SNAP) & (c.created_at_i >= T_SNAP - 540 * 86400)]
c = c[c.story_id.isin(ei.index)]
born = p.set_index("post_id").created_at_i
c["lat"] = c.created_at_i - c.story_id.map(born).to_numpy()
n = c.groupby("person").size()
people = n[n >= 10].index
c = c[c.person.isin(people)]
pi = pd.Series(np.arange(len(people)), index=people)
print("people", len(people), "comments", len(c), flush=True)
w = np.exp(-(T_SNAP - c.created_at_i.to_numpy()) / (180 * 86400) * np.log(2)).astype(np.float32)
taste = np.zeros((len(people), emb.shape[1]), np.float32)
np.add.at(taste, pi[c.person].to_numpy(), emb[ei[c.story_id].to_numpy()] * w[:, None])
taste /= np.linalg.norm(taste, axis=1, keepdims=True) + 1e-9
recent = c[c.created_at_i >= T_SNAP - 180 * 86400]
rate = (recent.groupby("person").size().reindex(people).fillna(0) / 180).to_numpy(np.float32)
hour = np.full((len(people), 24), 1.0, np.float32)                     # +1 smoothing
np.add.at(hour, (pi[recent.person].to_numpy(), ((recent.created_at_i // 3600) % 24).to_numpy()), 1)
hour /= hour.sum(1, keepdims=True)
scout = (c.assign(s=(c.lat <= 3600) & (c.lat >= 0)).groupby("person").s.mean().reindex(people).fillna(0)).to_numpy(np.float32)
print(f"scouts (share of comments within 60 min of posting > 0.3): {(scout > 0.3).sum()}", flush=True)

# ---- content prior: past stories ---------------------------------------------------------------------------------
past = p[(p.created_at_i < T_SNAP) & (p.points >= 3) & p.post_id.isin(ei.index)]
L = pd.concat([pd.read_json(os.path.join(H.CACHE, f), lines=True, dtype={"day": str}) for f in ("frontday.jsonl", "frontday_old.jsonl")])
top30 = set(L[L["rank"] <= 30].post_id)
past_emb = emb[ei[past.post_id].to_numpy()]
past_lp = np.log1p(past.points.to_numpy(np.float32))
past_100 = (past.points.to_numpy() >= 100).astype(np.float32)
past_t30 = past.post_id.isin(top30).to_numpy().astype(np.float32)
print("past stories for the content prior", len(past), flush=True)

# ---- posts to score ----------------------------------------------------------------------------------------------
q = p[(p.day >= "2026-07-01") & (p.day <= "2026-10-14") & p.post_id.isin(ei.index)].reset_index(drop=True)
qe = emb[ei[q.post_id].to_numpy()]
qh = ((q.created_at_i // 3600) % 24).to_numpy()
F = {k: np.zeros(len(q), np.float32) for k in ("aud_sum", "aud_cube", "aud_fans", "scout_sum", "scout_cube", "scout_fans",
                                                 "fans_any", "top50_sim", "knn_lp", "knn_100", "knn_t30", "knn_sim")}
W = rate[:, None] * hour                                           # people x 24: expected presence by hour
WS = W * scout[:, None]
CH = 512
for i in range(0, len(q), CH):
    sl = slice(i, i + CH)
    sim = qe[sl] @ taste.T                                        # posts x people
    rel = np.maximum(sim, 0)
    cube = rel ** 3
    fans = (sim > 0.6).astype(np.float32)
    hh = qh[sl]
    F["aud_sum"][sl] = np.einsum("ij,ji->i", rel, W[:, hh])
    F["aud_cube"][sl] = np.einsum("ij,ji->i", cube, W[:, hh])
    F["aud_fans"][sl] = np.einsum("ij,ji->i", fans, W[:, hh])
    F["scout_sum"][sl] = np.einsum("ij,ji->i", rel, WS[:, hh])
    F["scout_cube"][sl] = np.einsum("ij,ji->i", cube, WS[:, hh])
    F["scout_fans"][sl] = np.einsum("ij,ji->i", fans, WS[:, hh])
    F["fans_any"][sl] = fans.sum(1)
    F["top50_sim"][sl] = np.sort(sim, axis=1)[:, -50:].mean(1)
    ps = qe[sl] @ past_emb.T                                      # posts x past stories
    k = np.argpartition(-ps, 30, axis=1)[:, :30]
    F["knn_lp"][sl] = past_lp[k].mean(1)
    F["knn_100"][sl] = past_100[k].mean(1)
    F["knn_t30"][sl] = past_t30[k].mean(1)
    F["knn_sim"][sl] = np.take_along_axis(ps, k, 1).mean(1)
    if i % (CH * 20) == 0:
        print("scored", i, flush=True)
A = pd.DataFrame(F)
A["post_id"] = q.post_id.to_numpy()
pca = PCA(64, random_state=0).fit(qe[(q.day < "2026-09-01").to_numpy()])
Z = pd.DataFrame(pca.transform(qe), columns=[f"emb{j}" for j in range(64)])
A = pd.concat([A, Z], axis=1)
A.to_parquet(OUT, index=False)
print("saved", OUT, A.shape, flush=True)

# ---- at-posting evaluation ---------------------------------------------------------------------------------------
B = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"))
bcols = [x for x in B.columns if x.startswith("b_") and not x.startswith(("b_w30_", "b_w60_"))]
B = B[["post_id", "text_score"] + bcols].drop_duplicates("post_id")
q = q.merge(B, on="post_id", how="left").merge(A, on="post_id", how="left")
q["list_rank"] = q.post_id.map(L.groupby("post_id")["rank"].min()).fillna(999)
tr, te = (q.day < "2026-09-01").to_numpy(), (q.day >= "2026-09-01").to_numpy()
POST = ["text_score"] + bcols
AUD = ["aud_sum", "aud_cube", "aud_fans", "scout_sum", "scout_cube", "scout_fans", "fans_any", "top50_sim"]
KNN = ["knn_lp", "knn_100", "knn_t30", "knn_sim"]
EMB = [f"emb{j}" for j in range(64)]
SETS = {"post features (baseline)": POST, "+ content prior (30 nearest past titles)": POST + KNN,
        "+ title embedding (PCA 64)": POST + KNN + EMB, "+ audience simulation": POST + KNN + AUD,
        "+ audience + embedding": POST + KNN + AUD + EMB, "audience simulation alone": AUD + KNN}
rows = []
for top in (30, 10):
    y = (q.list_rank <= top).to_numpy()
    for name, cols in SETS.items():
        m = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8,
                               subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0).fit(q.loc[tr, cols], y[tr])
        s = m.predict_proba(q.loc[te, cols])[:, 1]
        P = q[te].assign(s=s, y=y[te])
        cap = np.mean([g.nlargest(top, "s").y.sum() / max(g.y.sum(), 1) for _, g in P.groupby("day")])
        cap100 = np.mean([g.nlargest(100, "s").y.sum() / max(g.y.sum(), 1) for _, g in P.groupby("day")])
        rows.append({"target": f"top {top}", "inputs": name, "AUC": round(roc_auc_score(y[te], s), 3),
                     "avg_precision": round(average_precision_score(y[te], s), 3),
                     "Brier": round(brier_score_loss(y[te], s), 4), f"winners_in_top{top}_per_day": round(cap, 3),
                     "winners_in_top100_per_day": round(cap100, 3)})
        print(json.dumps(rows[-1]), flush=True)
pd.DataFrame(rows).to_csv(os.path.join(H.CACHE, "audience_scores.csv"), index=False)
