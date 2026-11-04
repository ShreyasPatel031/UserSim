"""Checkpoint 1 (1 h), paired: the light model at 60 min (all 2025 + 2026 rows, content model, honest Wayback /newest votes
and comments by 60 min; WB_AGE=60 wb25_train.py -> wb25_scores_60.parquet) vs the 1-h headline on identical posts and
flag counts. The light model has no front-page rank (Quality News series start in June 2026, none for 2025).
  Sep 1 - Oct 14: headline = rank only + history score + content large, fit Jul-Aug (48.5%)
  Oct 2 - 14: headline inputs with a forward daily retrain (49.0%)
Plus the 50/50 rank blend (weights fixed in advance); by winner type.

    WB_AGE=60 python wb25_train.py && python paired60.py
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
import wb15 as W15
import wb_caught as W

LIGHT = "2025 + 2026 rows + content"


def line(name, T, s, ref, kind):
    c = W.caught_on(T, s)
    k = int(T.y.sum())
    fl = pd.Series(s).rank(ascending=False, method="first").to_numpy() <= k
    types = ", ".join(f"{t} {int((fl & (kind == t)).sum())}/{int((kind == t).sum())}" for t in ("fast", "late", "reup"))
    print(f"   {name:44s} {W.ci2(c)}" + ("" if ref is None else f"  vs headline {W.ci2(c, ref)}") + f" | {types}", flush=True)
    return c


def main():
    S = pd.read_parquet(os.path.join(H.CACHE, "wb25_scores_60.parquet"))
    Q = C.Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    C.Q = Q
    Q["content"] = Q.post_id.map(pd.read_parquet(os.path.join(H.CACHE, "content_scores_large_jun30.parquet")).drop_duplicates("post_id").set_index("post_id").s)
    full = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior", "content"]
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    R = C.honest(OL.vote_feats(Q, qb, [60])[60], 60, set(qb))[["rank_now", "best_rank"]]
    kind = CF.kinds(Q)
    rk = lambda v: pd.Series(np.asarray(v, float)).rank(pct=True).to_numpy()
    s0 = C.model(full, R)
    T = Q[C.te][["post_id", "day", "y"]].reset_index(drop=True)
    s1 = np.nan_to_num(T.post_id.map(S[S.test == "sep1_oct14"].drop_duplicates("post_id").set_index("post_id")[LIGHT]).to_numpy(), nan=-1)
    print(f"\nCaught at 1 h, Sep 1 - Oct 14 ({int(T.y.sum())} winners), identical posts and flags:", flush=True)
    ref = line("headline (rank + history + content, Jul-Aug)", T, s0, None, kind[C.te])
    line("light 60 min (2025 + 2026 rows + content)", T, s1, ref, kind[C.te])
    line("50/50 rank blend (fixed in advance)", T, 0.5 * rk(s0) + 0.5 * rk(s1), ref, kind[C.te])
    base = pd.concat([Q[full], R], axis=1)
    days = sorted(d for d in Q.day.unique() if "2026-10-02" <= d <= "2026-10-14")
    s2 = np.full(len(Q), np.nan)
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
        tt = (Q.day == d).to_numpy()
        s2[tt] = lgb.LGBMClassifier(**W15.PRM).fit(base[tr], Q.y[tr]).predict_proba(base[tt])[:, 1]
    sel = Q.day.isin(days).to_numpy()
    T2 = Q[sel][["post_id", "day", "y"]].reset_index(drop=True)
    s3 = np.nan_to_num(T2.post_id.map(S[S.test == "oct2_14"].drop_duplicates("post_id").set_index("post_id")[LIGHT]).to_numpy(), nan=-1)
    print(f"\nCaught at 1 h, Oct 2 - 14 ({int(T2.y.sum())} winners), forward daily retrain, identical posts and flags:", flush=True)
    ref2 = line("headline inputs (rank + history + content)", T2, s2[sel], None, kind[sel])
    line("light 60 min (2025 + 2026 rows + content)", T2, s3, ref2, kind[sel])
    line("50/50 rank blend (fixed in advance)", T2, 0.5 * rk(s2[sel]) + 0.5 * rk(s3), ref2, kind[sel])


if __name__ == "__main__":
    main()
