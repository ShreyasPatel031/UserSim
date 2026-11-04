"""Pre-registered gate / stacker of the two 15-min models (orchestrator, 2026-11-04), posting clock.
  fast  = headline model (votes + who + posts in the 30 min before + hour), forward daily retrain
  light = all 2025 + 2026 rows + content (wb25_train.py daily), forward daily retrain
Both scored out of sample on Sep 1 - Oct 14; within-day percentile ranks.
  (1) gate, no fitted parameters: fast rank for posts with an early /newest signal by 15 min (a snapshot with > 2 points,
      or a comment), light rank otherwise;
  (2) stacker: logistic regression on [rank fast, rank light, early signal, both interactions, snapshots on /newest by
      15 min, age at the last snapshot], fitted on Sep 1 - Oct 1 only.
Scored once on Oct 2 - 14, paired vs the 29.6% headline (fast) and vs light.

    python wb25_train.py daily && python gate15.py
"""
import os

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

import caught as C
import caught1h as C1
import content_ft as CF
import fine_io
import odds_live as OL
import pj_eval
import top100 as H
import wb15 as W15
import wb_caught as W


def main():
    Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    Q = Q.merge(pj_eval.judge_feats(), on="post_id", how="left")
    C.Q = Q
    kind = CF.kinds(Q)
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    R = C.honest(OL.vote_feats(Q, qb, [15])[15], 15, set(qb))[["rank_now", "best_rank"]]
    AT = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior"] + [c for c in Q.columns if c.startswith("pj_")]
    C1.Q = Q
    CM, WHO = C1.comments(15)
    V = W15.votes15(Q)
    X = pd.concat([Q[AT], R, CM[["cm_n", "cm_people", "cm_first"]], V, WHO, W15.expo15(Q)[["x_vol30", "x_hour"]]], axis=1)
    days = sorted(d for d in Q.day.unique() if "2026-09-01" <= d <= "2026-10-14")
    fast = np.full(len(Q), np.nan)
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
        tt = (Q.day == d).to_numpy()
        fast[tt] = lgb.LGBMClassifier(**W15.PRM).fit(X[tr], Q.y[tr]).predict_proba(X[tt])[:, 1]
    sel = Q.day.isin(days).to_numpy()
    T = Q[sel][["post_id", "day", "y"]].reset_index(drop=True)
    L = pd.read_parquet(os.path.join(H.CACHE, "wb25_daily_scores.parquet")).drop_duplicates("post_id").set_index("post_id").light
    T["fast"], T["light"] = fast[sel], T.post_id.map(L).to_numpy()
    print(f"posts {len(T)}, light scores for {T.light.notna().mean():.1%}", flush=True)
    T["light"] = T.light.fillna(T.light.min())
    T["pf"] = T.groupby("day").fast.rank(pct=True)
    T["pl"] = T.groupby("day").light.rank(pct=True)
    v = V[sel].reset_index(drop=True)
    cm = CM[sel].reset_index(drop=True)
    T["early"] = ((v.v_has == 1) & ((v.v_score.fillna(1) > 2) | (cm.cm_n.fillna(0) > 0))).astype(int).to_numpy()
    T["v_n"], T["v_age"] = v.v_n.fillna(0).to_numpy(), v.v_age.fillna(-1).to_numpy()
    T["gate"] = np.where(T.early == 1, T.pf, T.pl)
    F = ["pf", "pl", "early", "pf_e", "pl_e", "v_n", "v_age"]
    T["pf_e"], T["pl_e"] = T.pf * T.early, T.pl * T.early
    fit = (T.day <= "2026-10-01").to_numpy()
    te = (T.day >= "2026-10-02").to_numpy()
    lr = LogisticRegression(C=1.0, max_iter=2000).fit(T.loc[fit, F], T.y[fit])
    T["stack"] = lr.predict_proba(T[F])[:, 1]
    print("stacker fitted on Sep 1 - Oct 1:", dict(zip(F, np.round(lr.coef_[0], 2))), f"(early-signal rows in fit: {int(T.early[fit].sum())})", flush=True)
    Tt = T[te].reset_index(drop=True)
    kt = kind[sel][te]
    k = int(Tt.y.sum())
    print(f"\nCaught at 15 min (posting clock), Oct 2 - 14 ({k} winners), scored once:", flush=True)
    ref = W.caught_on(Tt, Tt.fast.to_numpy())
    lig = W.caught_on(Tt, Tt.light.to_numpy())
    for name, col in (("fast (headline)", "fast"), ("light", "light"), ("gate (pre-registered, no fit)", "gate"), ("stacker (fit Sep 1 - Oct 1)", "stack")):
        c = W.caught_on(Tt, Tt[col].to_numpy())
        flag = Tt[col].rank(ascending=False, method="first").to_numpy() <= k
        types = ", ".join(f"{t} {int((flag & (kt == t)).sum())}/{int((kt == t).sum())}" for t in ("fast", "late", "reup"))
        print(f"   {name:30s} {W.ci2(c)}  vs fast {W.ci2(c, ref)}  vs light {W.ci2(c, lig)} | {types}", flush=True)


if __name__ == "__main__":
    main()
