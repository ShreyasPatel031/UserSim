"""Intermediate target (orchestrator, 2026-11-02): predict each post's 15-min state on /newest from at-posting inputs,
then chain the prediction into the later checkpoints. Target (honest, Wayback /newest, outcome-independent capture):
log score at the /newest snapshot closest to 15 min (10-20 min), and whether it is on /news p1-3 by 20 min.
Training rows: posts with such a snapshot (Jul-Sep sample + Oct, posted before Oct 9); out-of-fold by day blocks for
those, a full-period model for every other post. Then, train <= Oct 8, test Oct 9-14, paired by day:
  checkpoint 3 (at posting): at-posting inputs, with vs without the predicted 15-min state
  checkpoint 1 (1 h): at-posting + front rank + comments + Wayback early votes (wb_caught), with vs without it
Reported as Caught (flags = winners) and pairwise accuracy (within-day AUC), on all days and 90%+ coverage days.

    python wb_chain.py
"""
import json
import os

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import caught as C
import fine_io
import odds_live as OL
import top100 as H
import wb_caught as W

PRM = dict(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8, subsample_freq=1,
           colsample_bytree=0.8, verbose=-1, random_state=0)


def target15(Q):
    A = pd.read_json(W.EV, lines=True, convert_dates=False)
    N = A[(A.page == "newest") & A.age_min.between(10, 20)].assign(d=lambda x: (x.age_min - 15).abs()).sort_values("d")
    N = N.drop_duplicates("item_id").set_index("item_id")
    off = {"news": 0, "news_p2": 30, "news_p3": 60}
    F = A[A.page.isin(off) & (A.age_min <= 20)]
    on = set(F.item_id)
    y_s = np.log1p(Q.post_id.map(N.score))
    y_f = Q.post_id.isin(on).astype(float).where(Q.post_id.isin(N.index))
    return y_s, y_f


def main():
    Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    import pj_eval
    Q = Q.merge(pj_eval.judge_feats(), on="post_id", how="left")
    PJ = [c for c in Q.columns if c.startswith("pj_")]
    AT = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior"] + PJ
    y_s, y_f = target15(Q)
    tr_all = (Q.day < "2026-10-09").to_numpy()
    has = y_s.notna().to_numpy()
    days = np.array(sorted(set(Q.day[tr_all & has])))
    fold = Q.day.map(pd.Series(np.arange(len(days)) * 5 // len(days), index=days)).to_numpy()
    P = pd.DataFrame(index=Q.index)
    for name, y in (("pred15_score", y_s), ("pred15_front", y_f)):
        y = y.to_numpy()
        pr = np.full(len(Q), np.nan)
        reg = lgb.LGBMRegressor(**PRM)
        for f in range(5):
            m = tr_all & has & (fold != f)
            pr[tr_all & has & (fold == f)] = lgb.LGBMRegressor(**PRM).fit(Q.loc[m, AT], y[m]).predict(Q.loc[tr_all & has & (fold == f), AT])
        rest = ~(tr_all & has)
        pr[rest] = reg.fit(Q.loc[tr_all & has, AT], y[tr_all & has]).predict(Q.loc[rest, AT])
        P[name] = pr
        te_ok = (~tr_all) & has
        print(f"{name}: training rows {int((tr_all & has).sum())}; test Spearman with the real 15-min value "
              f"{spearmanr(pr[te_ok], y[te_ok])[0]:.3f} ({int(te_ok.sum())} test posts)", flush=True)
    tr, te = tr_all, (Q.day >= "2026-10-09").to_numpy()
    T = Q[te][["post_id", "day", "y"]]
    good = T.day.isin(W.GOOD).to_numpy()
    _, qs = fine_io.load()
    q_by_id = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
               for r in qs.itertuples()}
    R = C.honest(OL.vote_feats(Q, q_by_id, [60])[60], 60, set(q_by_id))[["rank_now", "best_rank"]]
    X1 = pd.concat([Q[AT], R, W.comments_by(Q, 60), W.early(Q, 60)], axis=1)
    for label, X in (("checkpoint 3 (at posting)", Q[AT]), ("checkpoint 1 (1 h, with early votes)", X1)):
        s0 = lgb.LGBMClassifier(**PRM).fit(X[tr], Q.y[tr]).predict_proba(X[te])[:, 1]
        Xc = pd.concat([X, P], axis=1)
        s1 = lgb.LGBMClassifier(**PRM).fit(Xc[tr], Q.y[tr]).predict_proba(Xc[te])[:, 1]
        for sub, keep in (("all days", np.ones(len(T), bool)), ("90%+ coverage days", good)):
            c0, c1 = W.caught_on(T[keep], s0[keep]), W.caught_on(T[keep], s1[keep])
            print(f"{label}, Oct 9-14 {sub}: Caught without {W.ci2(c0)}; with predicted 15-min state {W.ci2(c1)}; "
                  f"difference {W.ci2(c1, c0)}", flush=True)
            print(f"   pairwise accuracy: without {C.pairwise(s0[keep], T=T[keep])}; with {C.pairwise(s1[keep], T=T[keep])}; "
                  f"difference {C.pairwise(s1[keep], s0[keep], T=T[keep])}", flush=True)


if __name__ == "__main__":
    main()
