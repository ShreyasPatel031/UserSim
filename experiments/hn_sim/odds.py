"""Calibrated odds per post: P(daily list top 30) and P(top 10) at posting and 15 / 30 / 60 min / 2 h after.

Inputs at posting: post features, 30 nearest past titles, title embedding, crowd v1 + v2 (audience.py, crowd_v2.py).
After posting, plus the post's own Quality News series up to that age (points, front-page rank, best rank, votes in
the last 30 / 60 min, upvote rate; as per_post.py). LightGBM fit on posts Jul 1 - Aug 15, isotonic calibration fit on
Aug 16 - 31, tested on Sep 1 - Oct 14. Reports AUC, Brier (vs base rate), and a calibration table (forecast band ->
how often it happened), and saves the models. -> <cache>/odds_models.pkl, odds_calibration.csv

    python odds.py
"""
import os
import pickle

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

import fine_io
import top100 as H

AGES = {"at posting": 0, "15 min": 15, "30 min": 30, "1 h": 60, "2 h": 120}
BANDS = [0, 0.01, 0.03, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]
p = H.stories()
p = p[(p.day >= "2026-07-01") & (p.day <= "2026-10-14")]
A = pd.read_parquet(os.path.join(H.CACHE, "audience_feats.parquet"))
B = pd.read_parquet(os.path.join(H.CACHE, "daily_cache.parquet"))
bcols = [x for x in B.columns if x.startswith("b_") and not x.startswith(("b_w30_", "b_w60_"))]
B = B[["post_id", "text_score"] + bcols].drop_duplicates("post_id")
F2 = pd.read_parquet(os.path.join(H.CACHE, "crowd_v2_feats.parquet"))
Q = p[["post_id", "day", "created_at_i"]].merge(B, on="post_id", how="left").merge(A, on="post_id", how="left").merge(F2, on="post_id", how="left").reset_index(drop=True)
L = pd.read_json(os.path.join(H.CACHE, "frontday.jsonl"), lines=True, dtype={"day": str})
Q["list_rank"] = Q.post_id.map(L.groupby("post_id")["rank"].min()).fillna(999)
BASE = (["text_score"] + bcols + ["knn_lp", "knn_100", "knn_t30", "knn_sim"] + [f"emb{j}" for j in range(64)]
        + ["aud_sum", "aud_cube", "aud_fans", "scout_sum", "scout_cube", "scout_fans", "fans_any", "top50_sim"]
        + ["c2_sum", "c2_scout", "c2_top50", "c2_n20"])

_, q = fine_io.load()
RK = np.array([[x if x is not None else 91 for x in r] for r in q.qn_rank_10m], np.float32)
UP = pd.DataFrame(list(q.qn_up_10m), dtype=float).ffill(axis=1).fillna(1).to_numpy(np.float32)
EX = pd.DataFrame(list(q.qn_exp_10m), dtype=float).ffill(axis=1).fillna(0).to_numpy(np.float32)
F0 = q.qn_f0.to_numpy().astype(float)
r = Q.post_id.map(pd.Series(np.arange(len(q)), index=q.post_id)).to_numpy()
has = ~np.isnan(r)
ri = np.where(has, r, 0).astype(int)
born = Q.created_at_i.to_numpy().astype(float)
fit = (Q.day < "2026-08-16").to_numpy()
cal = ((Q.day >= "2026-08-16") & (Q.day < "2026-09-01")).to_numpy()
te = (Q.day >= "2026-09-01").to_numpy()
print(f"posts: fit {fit.sum()}, calibrate {cal.sum()}, test {te.sum()}", flush=True)

models, tables = {}, []
for name, a in AGES.items():
    X = Q[BASE].copy()
    if a > 0:
        k = np.clip(np.floor((born + a * 60 - F0[ri]) / 600).astype(int), 0, 216)
        last = np.maximum(k - 1, 0)
        ok = has & (k > 0)
        pts = np.where(ok, UP[ri, last], 1)
        X["points"] = pts
        X["rank_now"] = np.where(ok, RK[ri, last], 91)
        X["best_rank"] = np.where(ok, np.where(np.arange(216)[None, :] < k[:, None], RK[ri], 91).min(1), 91)
        X["gain30"] = pts - np.where(ok & (k > 3), UP[ri, np.maximum(k - 4, 0)], 1)
        ex = np.where(ok, EX[ri, last], 0)
        X["rate"] = np.where(ex > 0.5, pts / np.maximum(ex, 1e-9), np.nan)
    for top in (30, 10):
        y = (Q.list_rank <= top).to_numpy()
        m = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8,
                               subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0).fit(X[fit], y[fit])
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(m.predict_proba(X[cal])[:, 1], y[cal])
        raw = m.predict_proba(X[te])[:, 1]
        s = iso.predict(raw)
        yt = y[te]
        models[(name, top)] = (m, iso, list(X.columns))
        band = pd.cut(s, BANDS, include_lowest=True)
        t = pd.DataFrame({"band": band, "p": s, "y": yt}).groupby("band", observed=True).agg(posts=("y", "size"), forecast=("p", "mean"), happened=("y", "mean"))
        t.insert(0, "target", f"top {top}")
        t.insert(0, "age", name)
        tables.append(t.reset_index())
        print(f"{name:10s} top {top}: AUC {roc_auc_score(yt, s):.3f}  Brier {brier_score_loss(yt, s):.4f} (raw {brier_score_loss(yt, raw):.4f}, "
              f"base rate {brier_score_loss(yt, np.full(len(yt), y[fit].mean())):.4f})  mean forecast {s.mean():.4f} vs actual {yt.mean():.4f}", flush=True)
T = pd.concat(tables, ignore_index=True)
T.to_csv(os.path.join(H.CACHE, "odds_calibration.csv"), index=False)
pickle.dump(models, open(os.path.join(H.CACHE, "odds_models.pkl"), "wb"))
pd.set_option("display.width", 200)
print(T[T.target == "top 30"].round(3).to_string(index=False))
