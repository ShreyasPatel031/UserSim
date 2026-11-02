"""Checkpoint 2 push (15 min after posting), honest early votes from Wayback /newest (October archive).
Forward test: for each posting day d in Oct 2-14, train on posts from Jul 1 to d-2 (so October's dense snapshot days
enter training as they pass), score day d's posts at 15 min. Flags = winners over Oct 2-14 (caught per post).

Inputs at 15 min:
  base     at-posting (post, similar titles, embedding, crowd, history score, page judge) + front-page rank by 15 min
           (Quality News; honest) + comments by 15 min
  votes    every /newest snapshot by 15 min: latest score, its age, votes per minute, best score, snapshots seen,
           rank on /newest (how fast it is being pushed down = posting volume), best /news rank (Wayback)
  who      who commented in the first 15 min: their record before Jul 1 (caught1h.comments)
  chain    predicted 15-min score from at-posting inputs (wb_chain idea), fit within each training window
Reported per variant: Caught over all days and over 90%+ coverage days, paired by day vs base.

    python wb15.py
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
import wb_caught as W

A_MIN = 15
PRM = dict(n_estimators=500, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8, subsample_freq=1,
           colsample_bytree=0.8, verbose=-1, random_state=0)


def votes15(Q):
    A = pd.read_json(W.EV, lines=True, convert_dates=False)
    A = A[(A.age_min >= 0) & (A.age_min <= A_MIN)]
    N = A[A.page == "newest"].sort_values("age_min")
    g = N.groupby("item_id")
    last = N.drop_duplicates("item_id", keep="last").set_index("item_id")
    off = {"news": 0, "news_p2": 30, "news_p3": 60}
    F = A[A.page.isin(off)]
    front = (F["rank"] + F.page.map(off)).groupby(F.item_id).min()
    out = pd.DataFrame(index=Q.index)
    out["v_has"] = Q.post_id.isin(last.index).astype(int)
    out["v_score"] = Q.post_id.map(last.score)
    out["v_age"] = Q.post_id.map(last.age_min)
    out["v_rate"] = (out.v_score - 1) / out.v_age.clip(lower=1)
    out["v_best"] = Q.post_id.map(g.score.max())
    out["v_n"] = Q.post_id.map(g.size()).fillna(0)
    out["v_rank_new"] = Q.post_id.map(last["rank"])
    out["v_push"] = out.v_rank_new / out.v_age.clip(lower=1)          # positions lost per minute on /newest
    out["v_comments"] = Q.post_id.map(last.comments)
    out["v_front"] = Q.post_id.map(front)
    return out


def main():
    Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    Q = Q.merge(pj_eval.judge_feats(), on="post_id", how="left")
    AT = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior"] + [c for c in Q.columns if c.startswith("pj_")]
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    R = C.honest(OL.vote_feats(Q, qb, [A_MIN])[A_MIN], A_MIN, set(qb))[["rank_now", "best_rank"]]
    C1.Q = Q
    CM, WHO = C1.comments(A_MIN)
    V = votes15(Q)
    y_s = np.log1p(V.v_score.where(V.v_age >= 10))                      # chain target: score at 10-15 min
    base = pd.concat([Q[AT], R, CM[["cm_n", "cm_people", "cm_first"]]], axis=1)
    variants = {"base": base, "+ votes": pd.concat([base, V], axis=1), "+ votes + who": pd.concat([base, V, WHO], axis=1)}
    days = sorted(d for d in Q.day.unique() if "2026-10-02" <= d <= "2026-10-14")
    scores = {k: np.full(len(Q), np.nan) for k in list(variants) + ["+ votes + who + chain"]}
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
        te = (Q.day == d).to_numpy()
        for k, X in variants.items():
            scores[k][te] = lgb.LGBMClassifier(**PRM).fit(X[tr], Q.y[tr]).predict_proba(X[te])[:, 1]
        # chain: predicted 15-min score from at-posting inputs, out-of-fold inside the training window
        ok = tr & y_s.notna().to_numpy()
        pr = np.full(len(Q), np.nan)
        fold = np.arange(len(Q)) % 3
        for f in range(3):
            m = ok & (fold != f)
            pr[tr & (fold == f)] = lgb.LGBMRegressor(**PRM).fit(Q.loc[m, AT], y_s[m]).predict(Q.loc[tr & (fold == f), AT])
        pr[te] = lgb.LGBMRegressor(**PRM).fit(Q.loc[ok, AT], y_s[ok]).predict(Q.loc[te, AT])
        X = pd.concat([variants["+ votes + who"], pd.Series(pr, index=Q.index, name="chain15")], axis=1)
        scores["+ votes + who + chain"][te] = lgb.LGBMClassifier(**PRM).fit(X[tr], Q.y[tr]).predict_proba(X[te])[:, 1]
        print(f"  {d}: trained on {int(tr.sum())} posts ({int(V.v_has[tr].sum())} with a /newest snapshot)", flush=True)
    sel = Q.day.isin(days).to_numpy()
    T = Q[sel][["post_id", "day", "y"]]
    good = T.day.isin(W.GOOD).to_numpy()
    print(f"Oct 2-14: {len(T)} posts, {int(T.y.sum())} winners; with a /newest snapshot by 15 min {V.v_has[sel].mean():.1%}", flush=True)
    for sub, keep in (("all days", np.ones(len(T), bool)), ("90%+ coverage days", good)):
        b = W.caught_on(T[keep], scores["base"][sel][keep])
        print(f"Caught at 15 min, {sub} ({T[keep].day.nunique()} days, {int(T.y[keep].sum())} winners): base {W.ci2(b)}", flush=True)
        for k in list(scores)[1:]:
            c = W.caught_on(T[keep], scores[k][sel][keep])
            print(f"   {k:24s} {W.ci2(c)}  vs base {W.ci2(c, b)}", flush=True)


if __name__ == "__main__":
    main()
