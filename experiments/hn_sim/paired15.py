"""Paired headline test at 15 min (posting clock; orchestrator, 2026-11-04): the light model (2025 Jan-Jun Wayback rows +
content; wb25_train.py, scores in wb25_scores.parquet) vs the headlines on identical posts and flag counts:
  Sep 1 - Oct 14 (fit <= Aug 31): vs 24.7% (caught.py headline: at-posting inputs + front-page rank by 15 min)
  Oct 2 - 14 (forward daily retrain): vs 29.6% (votes + who + posts in the 30 min before + hour; wb15)
Also the 50/50 rank blend of the two (weights fixed in advance), by winner type.

    python paired15.py
"""
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
import top100 as H
import wb15 as W15
import wb_caught as W

LIGHT = "2025 + 2026 rows + content"


def line(name, T, s, ref, kind):
    c = W.caught_on(T, s)
    k = int(T.y.sum())
    flag = pd.Series(s).rank(ascending=False, method="first").to_numpy() <= k
    types = ", ".join(f"{t} {int((flag & (kind == t)).sum())}/{int((kind == t).sum())}" for t in ("fast", "late", "reup"))
    print(f"   {name:46s} {W.ci2(c)}" + ("" if ref is None else f"  vs headline {W.ci2(c, ref)}") + f" | {types}", flush=True)
    return c


def main():
    S = pd.read_parquet(os.path.join(H.CACHE, "wb25_scores.parquet"))
    Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    Q = Q.merge(pj_eval.judge_feats(), on="post_id", how="left")
    C.Q = Q
    kind = CF.kinds(Q)
    rk = lambda v: pd.Series(np.asarray(v, float)).rank(pct=True).to_numpy()
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    R = C.honest(OL.vote_feats(Q, qb, [15])[15], 15, set(qb))[["rank_now", "best_rank"]]
    # (1) Sep 1 - Oct 14 vs 24.7%
    s0 = C.model(C.POST + C.KNN + C.EMB + C.CROWD, R)
    T = Q[C.te][["post_id", "day", "y"]].reset_index(drop=True)
    L1 = S[S.test == "sep1_oct14"].drop_duplicates("post_id").set_index("post_id")[LIGHT]
    s1 = T.post_id.map(L1).to_numpy()
    print(f"Sep 1 - Oct 14: {len(T)} posts, light-model scores for {np.isfinite(s1).mean():.1%}", flush=True)
    s1 = np.nan_to_num(s1, nan=-1)
    kt = kind[C.te]
    print(f"\nCaught at 15 min (posting clock), Sep 1 - Oct 14 ({int(T.y.sum())} winners), identical posts and flags:", flush=True)
    ref = line("headline (at posting + rank by 15 min)", T, s0, None, kt)
    line("light: 2025 + 2026 rows + content", T, s1, ref, kt)
    line("50/50 rank blend (fixed in advance)", T, 0.5 * rk(s0) + 0.5 * rk(s1), ref, kt)
    # (2) Oct 2 - 14 vs 29.6% (votes + who + volume + hour, forward daily retrain)
    AT = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior"] + [c for c in Q.columns if c.startswith("pj_")]
    C1.Q = Q
    CM, WHO = C1.comments(15)
    XP = W15.expo15(Q)[["x_vol30", "x_hour"]]
    X = pd.concat([Q[AT], R, CM[["cm_n", "cm_people", "cm_first"]], W15.votes15(Q), WHO, XP], axis=1)
    days = sorted(d for d in Q.day.unique() if "2026-10-02" <= d <= "2026-10-14")
    s2 = np.full(len(Q), np.nan)
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
        tt = (Q.day == d).to_numpy()
        s2[tt] = lgb.LGBMClassifier(**W15.PRM).fit(X[tr], Q.y[tr]).predict_proba(X[tt])[:, 1]
    sel = Q.day.isin(days).to_numpy()
    T2 = Q[sel][["post_id", "day", "y"]].reset_index(drop=True)
    L2 = S[S.test == "oct2_14"].drop_duplicates("post_id").set_index("post_id")[LIGHT]
    s3 = T2.post_id.map(L2).to_numpy()
    print(f"\nOct 2 - 14: {len(T2)} posts, light-model scores for {np.isfinite(s3).mean():.1%}", flush=True)
    s3 = np.nan_to_num(s3, nan=-1)
    k2 = kind[sel]
    print(f"Caught at 15 min (posting clock), Oct 2 - 14 ({int(T2.y.sum())} winners), identical posts and flags:", flush=True)
    ref2 = line("headline (votes + who + volume + hour)", T2, s2[sel], None, k2)
    line("light: 2025 + 2026 rows + content", T2, s3, ref2, k2)
    line("50/50 rank blend (fixed in advance)", T2, 0.5 * rk(s2[sel]) + 0.5 * rk(s3), ref2, k2)


if __name__ == "__main__":
    main()
