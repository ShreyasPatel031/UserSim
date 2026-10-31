"""Train the launch model on the day's order instead of vote counts. Same inputs, months and seeds as ctrl.py "all"
(rolling monthly, Mar-Oct, 5 seeds): LightGBM regression on log votes (as ctrl.py) vs LambdaRank within each day with
graded relevance from the real daily rank (top 3 = 4, 4-5 = 3, 6-10 = 2, 11-20 = 1, else 0), and their average.
GRID=1: a small sweep of model settings (leaves, trees, learning rate, inputs per tree), regression and LambdaRank.
usage: [GRID=1] python rank_launch.py -> results/rank_launch[_grid].json"""
import json, multiprocessing as mp, os
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd, lightgbm as lgb
import model as M, run as RN
from buildcache import build_cached

MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]


def rel(r):
    return np.select([r <= 3, r <= 5, r <= 10, r <= 20], [4, 3, 2, 1], 0)


GRID = {"base": dict(n_estimators=400, learning_rate=0.03, num_leaves=15, colsample_bytree=0.5, min_child_samples=20),
        "deeper": dict(n_estimators=600, learning_rate=0.02, num_leaves=31, colsample_bytree=0.5, min_child_samples=20),
        "shallow_more": dict(n_estimators=1200, learning_rate=0.01, num_leaves=7, colsample_bytree=0.5, min_child_samples=30),
        "fewer_inputs": dict(n_estimators=600, learning_rate=0.02, num_leaves=15, colsample_bytree=0.25, min_child_samples=20),
        "regularised": dict(n_estimators=800, learning_rate=0.02, num_leaves=15, colsample_bytree=0.5, min_child_samples=60)}


def job(a):
    m, tr, te, seed, cfg = a
    tr, te = M.add_fold_feats(tr, te)
    cols = M.cols(tr, M.LIVE_SOURCES + M.PAGE_SOURCES)
    kw = dict(GRID[cfg], subsample=0.8, subsample_freq=1, reg_lambda=1.0, random_state=seed, verbose=-1, n_jobs=1)
    reg = lgb.LGBMRegressor(**kw).fit(tr[cols], tr.logv).predict(te[cols])
    t2 = tr[tr.dailyRank.notna()].sort_values("day")
    rk = lgb.LGBMRanker(objective="lambdarank", lambdarank_truncation_level=20, **kw).fit(
        t2[cols], rel(t2.dailyRank.values), group=t2.groupby("day", sort=False).size().values).predict(te[cols])
    return pd.DataFrame({"id": te.id.values, "seed": seed, "cfg": cfg, "regression": reg, "lambdarank": rk})


def main():
    df = build_cached(); df = df[~df.known].copy()
    cfgs = list(GRID) if os.environ.get("GRID") == "1" else ["base"]
    jobs = [(m, tr, te, s, c) for m, tr, te in RN.folds(df, MONTHS) for s in range(5) for c in cfgs]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        P = pd.concat(pool.map(job, jobs))
    res = {}
    for c in cfgs:
        A = P[P.cfg == c].groupby("id")[["regression", "lambdarank"]].mean().reset_index().merge(df[["id", "day", "dailyRank"]], on="id")
        A = A[A.dailyRank.notna()]
        for v in ("regression", "lambdarank"):
            A[v + "_r"] = A.groupby("day")[v].rank(pct=True)
        A["average"] = A.regression_r + A.lambdarank_r
        for v in ("regression", "lambdarank", "average"):
            res[f"{c} {v}"] = [round(100 * np.mean(M.recall_at(A, "day", "dailyRank", k, v, per_list=True)), 1) for k in (3, 5, 10)]
        res["days"] = int(A.day.nunique())
    out = "results/rank_launch_grid.json" if os.environ.get("GRID") == "1" else "results/rank_launch.json"
    json.dump(res, open(out, "w"), indent=1); print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
