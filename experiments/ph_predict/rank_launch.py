"""Train the launch model on the day's order instead of vote counts. Same inputs, months and seeds as ctrl.py "all"
(rolling monthly, Mar-Oct, 5 seeds): LightGBM regression on log votes (as ctrl.py) vs LambdaRank within each day with
graded relevance from the real daily rank (top 3 = 4, 4-5 = 3, 6-10 = 2, 11-20 = 1, else 0), and their average.
usage: python rank_launch.py -> results/rank_launch.json"""
import json, multiprocessing as mp, os
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd, lightgbm as lgb
import model as M, run as RN
from buildcache import build_cached

MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]


def rel(r):
    return np.select([r <= 3, r <= 5, r <= 10, r <= 20], [4, 3, 2, 1], 0)


def job(a):
    m, tr, te, seed = a
    tr, te = M.add_fold_feats(tr, te)
    cols = M.cols(tr, M.LIVE_SOURCES + M.PAGE_SOURCES)
    kw = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
              colsample_bytree=0.5, reg_lambda=1.0, random_state=seed, verbose=-1, n_jobs=1)
    reg = lgb.LGBMRegressor(**kw).fit(tr[cols], tr.logv).predict(te[cols])
    t2 = tr[tr.dailyRank.notna()].sort_values("day")
    rk = lgb.LGBMRanker(objective="lambdarank", lambdarank_truncation_level=20, **kw).fit(
        t2[cols], rel(t2.dailyRank.values), group=t2.groupby("day", sort=False).size().values).predict(te[cols])
    return pd.DataFrame({"id": te.id.values, "seed": seed, "regression": reg, "lambdarank": rk})


def main():
    df = build_cached(); df = df[~df.known].copy()
    jobs = [(m, tr, te, s) for m, tr, te in RN.folds(df, MONTHS) for s in range(5)]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        P = pd.concat(pool.map(job, jobs))
    A = P.groupby("id")[["regression", "lambdarank"]].mean().reset_index().merge(df[["id", "day", "dailyRank"]], on="id")
    A = A[A.dailyRank.notna()]
    for c in ("regression", "lambdarank"):
        A[c + "_r"] = A.groupby("day")[c].rank(pct=True)
    A["average"] = A.regression_r + A.lambdarank_r
    res = {v: [round(100 * np.mean(M.recall_at(A, "day", "dailyRank", k, v, per_list=True)), 1) for k in (3, 5, 10)]
           for v in ("regression", "lambdarank", "average")}
    res["days"] = int(A.day.nunique())
    json.dump(res, open("results/rank_launch.json", "w"), indent=1); print(json.dumps(res))


if __name__ == "__main__":
    main()
