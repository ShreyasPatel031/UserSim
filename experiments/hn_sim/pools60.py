"""Checkpoint 1 (1 h), fix for the biggest error bucket (late risers): two-pool flag allocation, pre-registered.
Front-page status at 1 h is observable at 1 h. One ranking over all posts spends nearly every flag on posts already on
the front page (88% of those winners caught; late risers 56 / 461). Here:
  pool F = posts on the front page by 1 h (best rank <= 90, honest): ranked by the 1-h headline model
  pool O = posts not on the front page by 1 h: ranked by a model trained only on pool-O posts (same inputs)
  flags: total = winners (unchanged); pool O gets the share of winners that were in pool O in the TRAINING period
  (Jul-Aug), fixed before looking at the test; the rest go to pool F.
Paired vs the headline on identical posts and flag totals, Sep 1 - Oct 14 (and Oct 2-14 subset); by winner type.

    python pools60.py
"""
import os

import lightgbm as lgb
import numpy as np
import pandas as pd

import caught as C
import content_ft as CF
import fine_io
import odds_live as OL
import top100 as H
import wb_caught as W


def main():
    Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    C.Q = Q
    Q["content"] = Q.post_id.map(pd.read_parquet(os.path.join(H.CACHE, "content_scores_large_jun30.parquet")).drop_duplicates("post_id").set_index("post_id").s)
    full = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior", "content"]
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    R = C.honest(OL.vote_feats(Q, qb, [60])[60], 60, set(qb))[["rank_now", "best_rank"]]
    X = pd.concat([Q[full], R], axis=1)
    y = Q.y.to_numpy()
    off = R.best_rank.to_numpy() > 90
    fit, te = C.fit, C.te
    share_off = y[fit & off].sum() / y[fit].sum()                      # pre-registered from the training period
    s_head = C.model(full, R)                                          # headline: one ranking (test rows)
    m_off = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=31, min_child_samples=30, subsample=0.8,
                               subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0).fit(X[fit & off], y[fit & off])
    T = Q[te][["post_id", "day", "y"]].reset_index(drop=True)
    o = off[te]
    s_off = m_off.predict_proba(X[te])[:, 1]
    k = int(T.y.sum())
    k_off = int(round(share_off * k))
    flag = np.zeros(len(T), bool)
    rF = pd.Series(np.where(~o, s_head, -np.inf)).rank(ascending=False, method="first").to_numpy()
    rO = pd.Series(np.where(o, s_off, -np.inf)).rank(ascending=False, method="first").to_numpy()
    flag |= (~o) & (rF <= k - k_off)
    flag |= o & (rO <= k_off)
    kind = CF.kinds(Q)[te]
    w = T.y.to_numpy() == 1
    print(f"training-period share of winners off the front page by 1 h: {share_off:.1%} -> pool O gets {k_off} of {k} flags", flush=True)
    print(f"test: posts on the front page by 1 h {int((~o).sum())} ({int((w & ~o).sum())} winners); off {int(o.sum())} ({int((w & o).sum())} winners)", flush=True)
    # express both as per-day hit tables for the paired interval
    def table(fl):
        g = T.assign(f=fl).groupby("day")
        return pd.DataFrame({"hit": g.apply(lambda x: int((x.f & (x.y == 1)).sum())), "n": g.y.sum()})
    fh = pd.Series(s_head).rank(ascending=False, method="first").to_numpy() <= k
    c0, c1 = table(fh), table(flag)
    for name, fl, c in (("headline (one ranking)", fh, c0), ("two pools (pre-registered split)", flag, c1)):
        types = ", ".join(f"{t} {int((fl & (kind == t)).sum())}/{int((kind == t).sum())}" for t in ("fast", "late", "reup"))
        print(f"   {name:34s} {W.ci2(c)}" + ("" if c is c0 else f"  paired {W.ci2(c, c0)}") + f" | {types} | flags off-front {int((fl & o).sum())}", flush=True)
    oc = T.day.ge("2026-10-02").to_numpy()
    # Oct subset: same flags, restricted (the split was set for the whole test period)
    print(f"   Oct 2-14 subset (same flags): {W.ci2(c0.loc[c0.index >= '2026-10-02'])} -> {W.ci2(c1.loc[c1.index >= '2026-10-02'])}, "
          f"paired {W.ci2(c1.loc[c1.index >= '2026-10-02'], c0.loc[c0.index >= '2026-10-02'])}", flush=True)


if __name__ == "__main__":
    main()
