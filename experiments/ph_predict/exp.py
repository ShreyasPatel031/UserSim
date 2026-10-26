"""Fast model experiments on the same folds (Mar–Oct, train on earlier months only), all pre-launch sources.
Day list variants: regression on log votes (current), LambdaRank within day, per-k day classifiers, bigger/smaller
trees, and averages of ranks (ensembles). Week/month: per-k classifiers + stacking (as sizewin.py).
usage: python exp.py [extra sources ...]   -> results/exp.csv"""
import multiprocessing as mp, os, sys
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd, lightgbm as lgb
import model as M, run as RN
from compare_src import build_cached

EXTRA = [a for a in sys.argv[1:] if not a.startswith("--")] or ["fol", "seg", "promo"]
SRC = M.SOURCES + EXTRA
MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
P = dict(subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1, n_jobs=1)


def dayrank(te, s):
    return te.groupby("day")[s].rank(pct=True)


def fold(a):
    m, tr, te = a
    tr, te = M.add_fold_feats(tr, te); te = te.copy()
    c = M.cols(tr, SRC)
    out = te[["id", "day", "week", "mon", "dailyRank", "weeklyRank", "monthlyRank", "votes"]].copy()
    # day: regression variants
    for name, kw in {"reg": dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20),
                     "reg_big": dict(n_estimators=1200, learning_rate=0.01, num_leaves=31, min_child_samples=10),
                     "reg_small": dict(n_estimators=300, learning_rate=0.03, num_leaves=7, min_child_samples=40)}.items():
        out[name] = lgb.LGBMRegressor(**kw, **P).fit(tr[c], tr.logv).predict(te[c])
    # day: target = within-day percentile (removes day-level noise)
    yp = tr.groupby("day").logv.rank(pct=True)
    out["reg_pct"] = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, **P).fit(tr[c], yp).predict(te[c])
    # day: LambdaRank within day
    trs = tr.sort_values("day")
    rel = np.clip(11 - trs.dailyRank.fillna(99).values, 0, 10).astype(int)
    rk = lgb.LGBMRanker(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, **P)
    rk.fit(trs[c], rel, group=trs.groupby("day", sort=False).size().loc[trs.day.unique()].values)
    out["lambdarank"] = rk.predict(te[c])
    # day: per-k classifiers
    for k in (3, 5, 10):
        out[f"clf{k}"] = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, **P).fit(
            tr[c], (tr.dailyRank <= k).astype(int)).predict_proba(te[c])[:, 1]
    # ensembles (average within-day ranks)
    for s in ("reg", "reg_big", "reg_pct", "lambdarank", "clf3", "clf5", "clf10"):
        out[f"r_{s}"] = dayrank(out, s)
    out["ens_reg_rank"] = out.r_reg + out.r_lambdarank
    out["ens_all"] = out[[f"r_{s}" for s in ("reg", "reg_big", "reg_pct", "lambdarank", "clf5", "clf10")]].mean(1)
    print(m, flush=True)
    return out


def main():
    df = build_cached(); df = df[~df.known]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        T = pd.concat(pool.map(fold, list(RN.folds(df, MONTHS))))
    rows = []
    for s in ("reg", "reg_big", "reg_small", "reg_pct", "lambdarank", "clf3", "clf5", "clf10", "ens_reg_rank", "ens_all"):
        r = {"day score": s}
        for k in (3, 5, 10):
            r[f"day@{k}"] = round(100 * M.recall_at(T, "day", "dailyRank", k, s)[0], 1)
        rows.append(r)
    # per-k matched: use clfk for top k
    rows.append({"day score": "matched clf per k", **{f"day@{k}": round(100 * M.recall_at(T, "day", "dailyRank", k, f"clf{k}")[0], 1) for k in (3, 5, 10)}})
    out = pd.DataFrame(rows)
    out.to_csv("results/exp.csv", index=False)
    print("sources:", EXTRA); print(out.to_string(index=False))


if __name__ == "__main__":
    main()
