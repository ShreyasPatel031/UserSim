"""Where the daily model goes wrong: out-of-fold predictions for every launch (Mar-Oct, rolling monthly, 3 seeds averaged),
then hit rates and rank errors by launch type (brand, hunter, self-hunted, team size, ...).
usage: python resid.py [sources...]  -> results/resid.parquet + printed tables"""
import multiprocessing as mp, os, sys
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd
import model as M, run as RN
from buildcache import build_cached

BASE = M.SOURCES + ["fol", "seg", "promo", "rec", "busy"]
MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]


def job(a):
    m, tr, te, seed, src = a
    tr, te = M.add_fold_feats(tr, te)
    return pd.DataFrame({"id": te.id.values, "seed": seed, "s": M.fit_predict(tr, te, src, seed=seed)[0]})


def predict(df, src, seeds=3):
    jobs = [(m, tr, te, s, src) for m, tr, te in RN.folds(df, MONTHS) for s in range(seeds)]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        P = pd.concat(pool.map(job, jobs))
    return P.groupby("id").s.mean()


def table(D, col, bins=None, labels=None):
    g = pd.cut(D[col], bins, labels=labels) if bins is not None else D[col]
    T = D.groupby(g, observed=True).agg(n=("id", "size"), real_top3=("real3", "sum"), we_top3=("pred3", "sum"),
                                        hit=("hit3", "sum"), mean_err=("err", "mean"))
    T["share_of_real_top3_we_catch"] = (T.hit / T.real_top3).round(2)
    T["over_or_under"] = (T.we_top3 / T.real_top3).round(2)   # >1: we put too many of this type in our top 3
    return T


def main(src):
    df = build_cached(); df = df[~df.known & df.dailyRank.notna()].copy()
    df["s"] = df.id.map(predict(df, src))
    D = df[df.s.notna()].copy()
    D["pred_rank"] = D.groupby("day").s.rank(ascending=False, method="first")
    D["real3"], D["pred3"] = D.dailyRank <= 3, D.pred_rank <= 3
    D["hit3"] = D.real3 & D.pred3
    D["err"] = np.log2(D.pred_rank) - np.log2(D.dailyRank)        # >0: we ranked it worse than it did
    keep = ["id", "day", "name", "tagline", "dailyRank", "pred_rank", "s", "votes", "llm_brand", "llm_pitch", "ph_hunter_followers",
            "ph_maker_max_followers", "ph_self_hunted", "ph_n_makers", "hist_maker_n", "hist_hunter_n", "x_maker_max_followers",
            "x_company_followers", "cm_pre_users", "rec_c30", "fol_team", "promo_posts"]
    D[keep].to_parquet("results/resid.parquet")
    days = D.groupby("day").hit3.sum()
    print("daily top-3 hits per day:", days.value_counts().sort_index().to_dict(), " mean", round(days.mean() / 3 * 100, 1))
    for col, bins, labels in (("llm_brand", [-1, 0.5, 1.5, 2.5, 3.5], ["0 unknown", "1 niche", "2 known in niche", "3 famous"]),
                              ("ph_self_hunted", None, None), ("ph_n_makers", [-1, 0, 1, 3, 6, 99], ["0", "1", "2-3", "4-6", "7+"]),
                              ("ph_hunter_followers", [-1, 100, 1000, 10000, 50000, 1e9], ["<100", "100-1k", "1k-10k", "10k-50k", "50k+"]),
                              ("hist_maker_n", [-1, 0, 1, 3, 999], ["first launch", "1 before", "2-3", "4+"]),
                              ("x_maker_max_followers", [-1, 0, 1000, 10000, 1e9], ["no X", "<1k", "1k-10k", "10k+"])):
        print(f"\n== {col}\n", table(D, col, bins, labels).to_string())
    print("\nbiggest misses (real top 3, we ranked 10+):")
    print(D[D.real3 & (D.pred_rank >= 10)].sort_values("day")[["day", "name", "dailyRank", "pred_rank", "llm_brand", "ph_hunter_followers",
                                                             "ph_maker_max_followers", "ph_self_hunted", "hist_maker_n"]].tail(40).to_string())
    print("\nbiggest false alarms (we said top 3, it finished 15+):")
    print(D[D.pred3 & (D.dailyRank >= 15)].sort_values("day")[["day", "name", "dailyRank", "pred_rank", "llm_brand", "ph_hunter_followers",
                                                             "ph_n_makers", "ph_self_hunted"]].tail(40).to_string())


if __name__ == "__main__":
    main(BASE if len(sys.argv) < 2 else sys.argv[1:])
