"""Per-post forecast: a story is posted; at a fixed age (0 = at posting, then 15 min ... 4 h) what is the chance it
makes its day's daily list top 30 / top 10? Every story is on at most one day's list, so the label is just its best
list rank. Inputs at age a: what is known about the post itself at posting (title, domain, hour, submitter and domain
history, title text score; daily_cache.parquet) plus, for a > 0, its Quality News 10-minute series up to a (points,
rank on the front page, best rank, votes gained in the last 30 / 60 min, upvote rate).
Train: stories posted Jul 1 - Aug 31; test: Sep 1 - Oct 14 (lists settled). Stories with no Quality News page (they end
under ~5 points) get the no-votes fill (1 point, not on the page).

    python per_post.py
"""
import json
import os

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

import fine_io
import top100 as H

AGES = {"at posting": 0, "15 min": 15, "30 min": 30, "1 h": 60, "2 h": 120, "4 h": 240}
p = H.stories()
p = p[(p.day >= "2026-07-01") & (p.day <= "2026-10-14")].reset_index(drop=True)
L = pd.read_json(os.path.join(H.CACHE, "frontday.jsonl"), lines=True, dtype={"day": str})
best = L.groupby("post_id")["rank"].min()
p["list_rank"] = p.post_id.map(best).fillna(999)
B = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"))
bcols = [c for c in B.columns if c.startswith("b_") and not c.startswith(("b_w30_", "b_w60_"))]
B = B[["post_id", "text_score"] + bcols].drop_duplicates("post_id")
p = p.merge(B, on="post_id", how="left")
POST = ["text_score"] + bcols
_, q = fine_io.load()
RK = np.array([[x if x is not None else 91 for x in r] for r in q.qn_rank_10m], np.float32)
UP = pd.DataFrame(list(q.qn_up_10m), dtype=float).ffill(axis=1).fillna(1).to_numpy(np.float32)
EX = pd.DataFrame(list(q.qn_exp_10m), dtype=float).ffill(axis=1).fillna(0).to_numpy(np.float32)
F0 = q.qn_f0.to_numpy().astype(float)
qi = pd.Series(np.arange(len(q)), index=q.post_id)
r = p.post_id.map(qi).to_numpy()
has = ~np.isnan(r)
ri = np.where(has, r, 0).astype(int)
born = p.created_at_i.to_numpy().astype(float)
tr, te = (p.day < "2026-09-01").to_numpy(), (p.day >= "2026-09-01").to_numpy()
print(f"posts: train {tr.sum()}, test {te.sum()}; top 30 rate {np.mean(p.list_rank <= 30):.2%}, top 10 {np.mean(p.list_rank <= 10):.2%}", flush=True)
rows = []
for name, a in AGES.items():
    X = p[POST].copy()
    if a > 0:
        k = np.clip(np.floor((born + a * 60 - F0[ri]) / 600).astype(int), 0, 216)       # slots fully before age a
        last = np.maximum(k - 1, 0)
        ok = has & (k > 0)
        pts = np.where(ok, UP[ri, last], 1)
        X["points"] = pts
        X["rank_now"] = np.where(ok, RK[ri, last], 91)
        X["best_rank"] = np.where(ok, np.where(np.arange(216)[None, :] < k[:, None], RK[ri], 91).min(1), 91)
        X["gain30"] = pts - np.where(ok & (k > 3), UP[ri, np.maximum(k - 4, 0)], 1)
        X["gain60"] = pts - np.where(ok & (k > 6), UP[ri, np.maximum(k - 7, 0)], 1)
        ex = np.where(ok, EX[ri, last], 0)
        X["rate"] = np.where(ex > 0.5, pts / np.maximum(ex, 1e-9), np.nan)
    for top in (30, 10):
        y = (p.list_rank <= top).to_numpy()
        m = lgb.LGBMClassifier(n_estimators=500, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8,
                               subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0).fit(X[tr], y[tr])
        s = m.predict_proba(X[te])[:, 1]
        yt = y[te]
        hi = s >= 0.5
        rows.append({"age": name, "target": f"top {top}", "AUC": roc_auc_score(yt, s), "avg_precision": average_precision_score(yt, s),
                     "Brier": brier_score_loss(yt, s), "Brier_base": brier_score_loss(yt, np.full(len(yt), y[tr].mean())),
                     "flagged_>=50%": int(hi.sum()), "of_those_made_it": float(yt[hi].mean()) if hi.any() else np.nan,
                     "winners_caught_by_>=50%": float(hi[yt].mean())})
        print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in rows[-1].items()}), flush=True)
pd.DataFrame(rows).to_csv(os.path.join(H.CACHE, "per_post_scores.csv"), index=False)
