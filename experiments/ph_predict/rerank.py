"""Second stage for the day list: re-order each day's top contenders, where the model's order flips.
Stage 1: the regression on log votes (all sources), out-of-fold on the training months.
Stage 2: LambdaRank within each day over the stage-1 top N, on stage-1 score/rank/gap plus the inputs that differ in
reversals (team community activity: rec_, fol_, seg_, busy_, number of makers). Compared: rec only (dated comments,
leak-free) vs + followers (follow lists read today, may include follows made after the launch).
usage: python rerank.py -> results/rerank.csv"""
import multiprocessing as mp, os
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd, lightgbm as lgb
import model as M, run as RN
from buildcache import build_cached

MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
N = 12
P = dict(subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=0, verbose=-1, n_jobs=1)
REG = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20)
SETS = {"rec": ["rec_"], "rec+fol": ["rec_", "fol_", "busy_"], "rec+fol+seg": ["rec_", "fol_", "busy_", "seg_"]}


def s1(tr, te, c):
    return lgb.LGBMRegressor(**REG, **P).fit(tr[c], tr.logv).predict(te[c])


def contenders(d):
    d = d.copy()
    d["s1_rank"] = d.groupby("day").s1.rank(ascending=False, method="first")
    d["s1_gap"] = d.s1 - d.groupby("day").s1.transform("max")
    d["s1_pct"] = d.groupby("day").s1.rank(pct=True)
    return d


def fold(a):
    m, tr, te = a
    tr, te = M.add_fold_feats(tr, te); te = te.copy()
    c = M.cols(tr, M.SOURCES + ["fol", "seg", "promo", "rec", "busy"])
    oof = []
    for mm in sorted(tr.mon.unique()):
        x, y = tr[tr.mon != mm], tr[tr.mon == mm]
        if len(x) > 200:
            oof.append(pd.Series(s1(x, y, c), index=y.index))
    tr2 = contenders(tr.loc[pd.concat(oof).index].assign(s1=pd.concat(oof)))
    te2 = contenders(te.assign(s1=s1(tr, te, c)))
    out = te2[["id", "day", "dailyRank", "s1", "s1_rank"]].copy()
    for name, pref in SETS.items():
        f = ["s1", "s1_rank", "s1_gap", "s1_pct", "ph_n_makers", "ph_hunter_followers", "ph_day_n_launches"] + \
            [x for x in c if any(x.startswith(p) for p in pref)]
        a_ = tr2[tr2.s1_rank <= N].sort_values("day")
        rel = np.clip(11 - a_.dailyRank.fillna(99).values, 0, 10).astype(int)
        rk = lgb.LGBMRanker(n_estimators=300, learning_rate=0.03, num_leaves=7, min_child_samples=30, **P)
        rk.fit(a_[f], rel, group=a_.groupby("day", sort=False).size().loc[a_.day.unique()].values)
        sc = rk.predict(te2[f])
        # contenders re-ordered by stage 2; everyone else keeps stage-1 order below them
        out[f"rr|{name}"] = np.where(te2.s1_rank <= N, 1000 + sc, te2.s1)
    print(m, flush=True)
    return out


def main():
    df = build_cached(); df = df[~df.known]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        T = pd.concat(pool.map(fold, list(RN.folds(df, MONTHS))))
    rows = []
    for s in ["s1"] + [f"rr|{k}" for k in SETS]:
        rows.append({"day score": s, **{f"day@{k}": round(100 * M.recall_at(T, "day", "dailyRank", k, s)[0], 1) for k in (3, 5, 10)}})
    out = pd.DataFrame(rows); out.to_csv("results/rerank.csv", index=False); print(out.to_string(index=False))
    T[["id", "s1"]].rename(columns={"s1": "pred"}).to_csv("results/pred_all_sources.csv", index=False)


if __name__ == "__main__":
    main()
