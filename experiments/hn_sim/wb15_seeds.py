"""Checkpoint 2: is the 15-min model limited by its own variance? Same inputs as the current best (votes + who +
exposure; wb15.py), Oct 2-14 forward daily retrain, scored with 1 model vs the average of 5 seeds (bagging), and a
slower / more regularised setting. Paired vs the single model.

    python wb15_seeds.py
"""
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import caught as C
import caught1h as C1
import fine_io
import odds_live as OL
import pj_eval
import top100 as H
import wb15 as W15
import wb_caught as W


def main():
    Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    Q = Q.merge(pj_eval.judge_feats(), on="post_id", how="left")
    AT = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior"] + [c for c in Q.columns if c.startswith("pj_")]
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    R = C.honest(OL.vote_feats(Q, qb, [15])[15], 15, set(qb))[["rank_now", "best_rank"]]
    C1.Q = Q
    CM, WHO = C1.comments(15)
    X = pd.concat([Q[AT], R, CM[["cm_n", "cm_people", "cm_first"]], W15.votes15(Q), WHO, W15.expo15(Q)], axis=1)
    y = Q.y.to_numpy()
    days = sorted(d for d in Q.day.unique() if "2026-10-02" <= d <= "2026-10-14")
    sel = Q.day.isin(days).to_numpy()
    setups = {"single": [dict(W15.PRM)],
              "5 seeds": [dict(W15.PRM, random_state=s) for s in range(5)],
              "5 seeds, slower + regularised": [dict(W15.PRM, random_state=s, n_estimators=1000, learning_rate=0.015, num_leaves=15,
                                                     min_child_samples=60, reg_lambda=5.0, colsample_bytree=0.5) for s in range(5)]}
    S = {k: np.full(len(Q), np.nan) for k in setups}
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
        te = (Q.day == d).to_numpy()
        for k, ps in setups.items():
            S[k][te] = np.mean([lgb.LGBMClassifier(**p).fit(X[tr], y[tr]).predict_proba(X[te])[:, 1] for p in ps], axis=0)
        print(f"  {d}", flush=True)
    T = Q[sel][["post_id", "day", "y"]].reset_index(drop=True)
    base = W.caught_on(T, S["single"][sel])
    print(f"Caught at 15 min, Oct 2-14: single model {W.ci2(base)}", flush=True)
    for k in list(setups)[1:]:
        c = W.caught_on(T, S[k][sel])
        print(f"   {k:32s} {W.ci2(c)}  vs single {W.ci2(c, base)}", flush=True)


if __name__ == "__main__":
    main()
