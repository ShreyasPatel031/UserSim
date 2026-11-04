"""Checkpoint 1 (1 h): what the live per-minute model will see, backtested on the dense October Wayback archive.
(A) Miss decomposition of the 1-h headline (rank only + history score + content model large, Sep 1 - Oct 14, 48.5%):
    re-up / late riser (no front page by 1 h) / on the front page by 1 h but ranked below the cut; oracle gains.
(B) Oct 2 - 14, forward daily retrain, paired: the 1-h headline inputs vs + honest early votes by 60 min (Wayback /newest
    and /news captures: points, rate, /newest position, best front position, captures seen) + comments and who commented
    by 60 min. Wayback capture timing does not depend on the outcome (checked for Oct 2026 and all of 2025).

    python hour60.py
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
import store as S
import top100 as H
import wb15 as W15
import wb_caught as W


def main():
    os.environ["HIST"] = "1"
    Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    C.Q = Q
    f = os.path.join(H.CACHE, "content_scores_large_jun30.parquet")
    if not os.path.exists(f):
        S._bucket().get_blob(CF.PFX + "scores_large_jun30.parquet").download_to_filename(f)
    Q["content"] = Q.post_id.map(pd.read_parquet(f).drop_duplicates("post_id").set_index("post_id").s)
    full = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior", "content"]
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    R = C.honest(OL.vote_feats(Q, qb, [60])[60], 60, set(qb))[["rank_now", "best_rank"]]
    kind = CF.kinds(Q)
    # (A) decomposition of the 1-h headline on Sep 1 - Oct 14
    s = C.model(full, R)
    T = Q[C.te][["post_id", "day", "y"]].reset_index(drop=True)
    k = int(T.y.sum())
    flag = pd.Series(s).rank(ascending=False, method="first").to_numpy() <= k
    kt = kind[C.te]
    w = T.y.to_numpy() == 1
    b = np.select([kt == "reup", kt == "late"], ["re-up (first listed 2+ days after posting)", "late riser (no front page by 1 h)"],
                  "on the front page by 1 h")
    D = pd.DataFrame({"bucket": b, "w": w, "flag": flag})
    tab = D[D.w].groupby("bucket").agg(winners=("w", "size"), caught=("flag", "sum"))
    tab["missed"] = tab.winners - tab.caught
    tab["oracle_gain_pts"] = (100 * tab.missed / k).round(1)
    print(f"(A) 1-h headline (rank only + history + content), Sep 1 - Oct 14: {int((flag & w).sum())}/{k} = {(flag & w).sum() / k:.1%}")
    print(tab.sort_values("missed", ascending=False).to_string(), flush=True)
    # (B) Oct 2 - 14 daily retrain: + honest votes / comments / who by 60 min
    W15.A_MIN = 60
    V = W15.votes15(Q).add_suffix("_60")
    C1.Q = Q
    CM, WHO = C1.comments(60)
    base = pd.concat([Q[full], R], axis=1)
    X1 = pd.concat([base, V, CM[["cm_n", "cm_people", "cm_first"]], WHO], axis=1)
    days = sorted(d for d in Q.day.unique() if "2026-10-02" <= d <= "2026-10-14")
    s0, s1 = np.full(len(Q), np.nan), np.full(len(Q), np.nan)
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
        tt = (Q.day == d).to_numpy()
        s0[tt] = lgb.LGBMClassifier(**W15.PRM).fit(base[tr], Q.y[tr]).predict_proba(base[tt])[:, 1]
        s1[tt] = lgb.LGBMClassifier(**W15.PRM).fit(X1[tr], Q.y[tr]).predict_proba(X1[tt])[:, 1]
    sel = Q.day.isin(days).to_numpy()
    T2 = Q[sel][["post_id", "day", "y"]].reset_index(drop=True)
    k2 = int(T2.y.sum())
    print(f"\n(B) Caught at 1 h, Oct 2 - 14 daily retrain ({k2} winners); Wayback snapshot by 60 min for "
          f"{V.v_has_60[sel].mean():.1%} of posts, {V.v_has_60[sel & (Q.y == 1).to_numpy()].mean():.1%} of winners:", flush=True)
    c0, c1 = W.caught_on(T2, s0[sel]), W.caught_on(T2, s1[sel])
    for name, sc, c in (("1-h headline inputs (rank only + history + content)", s0[sel], c0),
                        ("+ votes, comments, who by 60 min (honest)", s1[sel], c1)):
        fl = pd.Series(sc).rank(ascending=False, method="first").to_numpy() <= k2
        types = ", ".join(f"{t} {int((fl & (kind[sel] == t)).sum())}/{int((kind[sel] == t).sum())}" for t in ("fast", "late", "reup"))
        print(f"   {name:52s} {W.ci2(c)}" + ("" if c is c0 else f"  vs base {W.ci2(c, c0)}") + f" | {types}", flush=True)

    # (C) only posts NOT on the front page by 1 h (where late risers and re-ups are): does anything visible by 1 h
    # separate the future winners from the posts that never rise? Daily retrain on that subset, AUC + Caught within it.
    from sklearn.metrics import roc_auc_score
    off = (R.best_rank.to_numpy() > 90)
    t0, t1 = np.full(len(Q), np.nan), np.full(len(Q), np.nan)
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy() & off
        tt = (Q.day == d).to_numpy() & off
        t0[tt] = lgb.LGBMClassifier(**W15.PRM).fit(base[tr], Q.y[tr]).predict_proba(base[tt])[:, 1]
        t1[tt] = lgb.LGBMClassifier(**W15.PRM).fit(X1[tr], Q.y[tr]).predict_proba(X1[tt])[:, 1]
    so = sel & off
    T3 = Q[so][["post_id", "day", "y"]].reset_index(drop=True)
    print(f"\n(C) posts not on the front page by 1 h, Oct 2 - 14: {len(T3)} posts, {int(T3.y.sum())} winners "
          f"(late risers + re-ups + a few fast by other measures); Wayback snapshot by 60 min {V.v_has_60[so].mean():.1%}", flush=True)
    a0, a1 = roc_auc_score(T3.y, t0[so]), roc_auc_score(T3.y, t1[so])
    d0, d1 = W.caught_on(T3, t0[so]), W.caught_on(T3, t1[so])
    print(f"   AUC within the subset: base {a0:.3f} -> + votes/comments/who {a1:.3f}", flush=True)
    print(f"   Caught within the subset (flags = its winners): base {W.ci2(d0)} -> + votes/comments/who {W.ci2(d1)}, "
          f"paired {W.ci2(d1, d0)}", flush=True)
    imp = pd.Series(lgb.LGBMClassifier(**W15.PRM).fit(X1[(Q.day <= "2026-10-12").to_numpy() & off], Q.y[(Q.day <= "2026-10-12").to_numpy() & off])
                    .booster_.feature_importance("gain"), index=X1.columns).sort_values(ascending=False)
    print("   top inputs (gain) in the subset model:", ", ".join(f"{i} {v:.0f}" for i, v in imp.head(10).items()), flush=True)


if __name__ == "__main__":
    main()
