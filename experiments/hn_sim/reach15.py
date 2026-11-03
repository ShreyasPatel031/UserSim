"""E5's September reach table (P(top-30 reach within 24 h | 15-min /newest score), fitted Sep 1-30 only) as a 15-min
input to votes + who (28.4%), Oct 2-14 forward daily retrain, paired, by winner type.

    python reach15.py
"""
import json
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import caught as C
import caught1h as C1
import content_ft as CF
import fine_io
import odds_live as OL
import pj_eval
import store as S
import top100 as H
import wb15 as W15
import wb_caught as W

d = json.loads(S._bucket().get_blob("usersim_sim/hn_jobs/cache/e5_handoff/hn_handoff_e5.json").download_as_text())
rate = d["reach_table_by_15min_score_sep"]["real_rate"]
Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
Q = Q.merge(pj_eval.judge_feats(), on="post_id", how="left")
AT = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior"] + [c for c in Q.columns if c.startswith("pj_")]
_, qs = fine_io.load()
qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
      for r in qs.itertuples()}
R = C.honest(OL.vote_feats(Q, qb, [15])[15], 15, set(qb))[["rank_now", "best_rank"]]
C1.Q = Q
CM, WHO = C1.comments(15)
V = W15.votes15(Q)
base = pd.concat([Q[AT], R, CM[["cm_n", "cm_people", "cm_first"]], V, WHO], axis=1)
v = V.v_score.to_numpy(float)
reach = np.where(np.isnan(v) | (v < 1), np.nan, np.where(v >= 4, rate["4+"], np.vectorize(lambda x: rate.get(str(int(x)), np.nan))(np.nan_to_num(v, nan=1))))
X1 = base.assign(reach_sep=reach)
y = Q.y.to_numpy()
kind = CF.kinds(Q)
days = sorted(x for x in Q.day.unique() if "2026-10-02" <= x <= "2026-10-14")
s0, s1 = np.full(len(Q), np.nan), np.full(len(Q), np.nan)
for dd in days:
    tr = (Q.day <= (pd.Timestamp(dd) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
    tt = (Q.day == dd).to_numpy()
    s0[tt] = lgb.LGBMClassifier(**W15.PRM).fit(base[tr], y[tr]).predict_proba(base[tt])[:, 1]
    s1[tt] = lgb.LGBMClassifier(**W15.PRM).fit(X1[tr], y[tr]).predict_proba(X1[tt])[:, 1]
sel = Q.day.isin(days).to_numpy()
T = Q[sel][["post_id", "day", "y"]].reset_index(drop=True)
c0, c1 = W.caught_on(T, s0[sel]), W.caught_on(T, s1[sel])
print(f"15 MIN (Oct 2-14, {int(T.y.sum())} winners): votes + who {W.ci2(c0)} | by type {CF.by_type(T, s0[sel], kind[sel])}", flush=True)
print(f"   + E5 reach table (Sep fit): {W.ci2(c1)}, difference {W.ci2(c1, c0)} | by type {CF.by_type(T, s1[sel], kind[sel])}", flush=True)
