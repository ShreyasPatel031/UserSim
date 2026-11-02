"""Late risers at 15 min (orchestrator, 2026-11-02): winners that were not on the front page by 1 h and still made the
posting day's or the next day's list look like non-winners on /newest at 15 min. A model just for "slow start but
makes it": trained on posts with a slow start (<= 2 points at the latest /newest snapshot by 15 min, not on the front
page by 15 min), label = late riser (vs any non-winner), inputs = everything wb15 has at 15 min (at-posting incl.
history score and page judge, rank, comments, /newest votes, who commented early). Forward daily retrain, Oct 2-14.
Reported:
  - late risers caught among slow-start posts, same number of flags as late risers there: general 15-min model
    (wb15 "+ votes + who") vs the late-riser model
  - Caught at 15 min per post (all winners): general model vs the general model with the late-riser model's ranking
    swapped in for the slow-start posts (rank-blended 50/50), flags = winners
Also the re-up clock view (live data in live15.py): re-ups judged at their re-up time; here only the archive numbers.

    python wb_late.py     # needs wb15_scores.parquet (wb15.py)
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

PRM = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8, subsample_freq=1,
           colsample_bytree=0.8, verbose=-1, random_state=0)


def main():
    Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    Q = Q.merge(pj_eval.judge_feats(), on="post_id", how="left")
    AT = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior"] + [c for c in Q.columns if c.startswith("pj_")]
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    R = C.honest(OL.vote_feats(Q, qb, [15])[15], 15, set(qb))[["rank_now", "best_rank"]]
    vis60 = (OL.vote_feats(Q, qb, [60])[60].best_rank <= 30).to_numpy()
    C1.Q = Q
    CM, WHO = C1.comments(15)
    V = W15.votes15(Q)
    X = pd.concat([Q[AT], R, CM[["cm_n", "cm_people", "cm_first"]], V, WHO], axis=1)
    L = OL.lists()
    first = L[L["rank"] <= 30].groupby("post_id").day.min()
    lag = (pd.to_datetime(Q.post_id.map(first)) - pd.to_datetime(Q.day)).dt.days.to_numpy()
    y = Q.y.to_numpy()
    kind = np.where(y == 0, "none", np.where(lag >= 2, "reup", np.where(vis60, "fast", "late")))
    late = (kind == "late").astype(int)
    slow = ((V.v_score.fillna(1) <= 2) & (V.v_front.isna()) & (R.best_rank > 30)).to_numpy()
    days = sorted(d for d in Q.day.unique() if "2026-10-02" <= d <= "2026-10-14")
    s_late = np.full(len(Q), np.nan)
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy() & slow
        te = (Q.day == d).to_numpy()
        s_late[te] = lgb.LGBMClassifier(**PRM).fit(X[tr], late[tr]).predict_proba(X[te])[:, 1]
    G = pd.read_parquet(os.path.join(H.CACHE, "wb15_scores.parquet"))
    sel = Q.day.isin(days).to_numpy()
    T = Q[sel][["post_id", "day", "y"]].reset_index(drop=True)
    g = T.post_id.map(G.set_index("post_id")["+ votes + who"]).to_numpy()
    sl, ks, sw = s_late[sel], kind[sel], slow[sel]
    n_late = int(((ks == "late") & sw).sum())
    print(f"Oct 2-14: slow-start posts {int(sw.sum())} of {len(T)}; late risers {int((ks == 'late').sum())}, "
          f"of them slow-start {n_late}; fast winners with a slow start {int(((ks == 'fast') & sw).sum())}", flush=True)
    for name, s in (("general 15-min model", g), ("late-riser model", sl)):
        r = pd.Series(np.where(sw, s, -np.inf)).rank(ascending=False, method="first").to_numpy()
        print(f"   among slow-start posts, flags = {n_late}: {name} catches {int(((r <= n_late) & (ks == 'late')).sum())} "
              f"late risers", flush=True)
    base = W.caught_on(T, g)
    rk = lambda x: pd.Series(x).rank(pct=True).to_numpy()
    for w in (0.25, 0.5):
        comb = np.where(sw, (1 - w) * rk(g) + w * rk(np.nan_to_num(sl)), rk(g))
        c = W.caught_on(T, comb)
        k = int(T.y.sum())
        f = pd.Series(comb).rank(ascending=False, method="first").to_numpy() <= k
        print(f"Caught at 15 min, general + late-riser model on slow starts (weight {w}): {W.ci2(c)} vs general {W.ci2(base)}; "
              f"difference {W.ci2(c, base)}; caught by type: " +
              ", ".join(f"{t} {int((f & (ks == t)).sum())}/{int((ks == t).sum())}" for t in ("fast", "late", "reup")), flush=True)


if __name__ == "__main__":
    main()
