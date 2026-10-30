"""Error analysis for the best scoreboard model (post + early 30/60 + who + submitter), September 2026:
which real top-10 stories the model ranks low, and what they have in common (domain, early comments, type).
Saves the September predictions to <cache>/pred_sep.parquet for later event-level scoring."""
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import top10 as T
import top100 as H

p = H.stories()
p = p[(p.month >= "2023-03") & (p.month <= "2026-09")].reset_index(drop=True)
y = np.log1p(p.points.to_numpy())
rk = p.groupby("day").points.rank(ascending=False, method="first").to_numpy()
blocks = ["post", "early30", "who30", "early60", "who60", "submitter"]
X = pd.concat([pd.read_parquet(os.path.join(H.CACHE, H.BLOCK_FILES[b] + ".parquet")).drop_duplicates("post_id")
               .set_index("post_id").reindex(p.post_id).reset_index(drop=True) for b in blocks], axis=1)
tr, te = (p.month < "2026-09").to_numpy(), (p.month == "2026-09").to_numpy()
oof, txt = T.text_scores(p, y, tr, te)
keep = (rk <= 100) | (np.random.default_rng(0).random(len(p)) < 0.25)
c = lgb.LGBMClassifier(**{**H.GBM, "n_jobs": 4, "scale_pos_weight": 2})
c.fit(X[tr].assign(text_score=oof)[keep[tr]], (rk[tr & keep] <= 100).astype(int))
s = c.predict_proba(X[te].assign(text_score=txt))[:, 1]
P = p[te][["post_id", "day", "title", "url", "points", "created_at_i"]].assign(score=s, rk=rk[te],
                                                                           e60=X[te].e60_all.to_numpy(),
                                                                           e30=X[te].e30_all.to_numpy())
P["pred_rank"] = P.groupby("day").score.rank(ascending=False, method="first")
P.to_parquet(os.path.join(H.CACHE, "pred_sep.parquet"), index=False)
top = P[P.rk <= 10]
print("real top-10 stories:", len(top), " found in model top 10:", int((top.pred_rank <= 10).sum()),
      " in top 30:", int((top.pred_rank <= 30).sum()), " in top 100:", int((top.pred_rank <= 100).sum()))
miss = top[top.pred_rank > 100]
print("\nmissed (model rank > 100):", len(miss))
print("median comments in 60 min: hit", top[top.pred_rank <= 10].e60.median(), " missed", miss.e60.median())
host = lambda u: (u or "").split("/")[2].removeprefix("www.") if isinstance(u, str) and u.count("/") >= 2 else "self"  # noqa: E731
print("missed hosts:", miss.url.map(host).value_counts().head(12).to_dict())
print("ask/show/tell:", miss.title.str.match(r"^(Ask|Show|Tell) HN").sum())
print(miss.sort_values("points", ascending=False)[["day", "points", "pred_rank", "e30", "e60", "title"]].head(25).to_string())
