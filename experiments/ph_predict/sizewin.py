"""Week / month lists: predict how big a launch gets compared with other days, not just who wins its day.

Stage 1 (per fold, out-of-fold on the training months so stage 2 learns from honest predictions):
  r    predicted log votes            p1 / p3   chance of finishing #1 / top 3 of its day
Stage 2: classifiers for "in the week's / month's top k", one per k (3, 5, 10), on all launch inputs + stage-1
  outputs + their standing within the day, week and month. A launch's week/month peers are known in advance
  (scheduled launches), their votes are not used.
Also: the same per-k classifiers without stage 1 ("direct"), to see which part helps.
Output: results/sizewin.csv"""
import multiprocessing as mp, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
import features as F, model as M, run as RN

MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
SRC = M.SOURCES + ["fol"]
KS = (3, 5, 10)
P = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
         colsample_bytree=0.8, random_state=0, verbose=-1, n_jobs=1)


def stage1(tr, te, c):
    """Fit on tr, predict te: log votes, P(#1 of day), P(top 3 of day)."""
    out = pd.DataFrame(index=te.index)
    out["s1_r"] = lgb.LGBMRegressor(**P).fit(tr[c], tr.logv).predict(te[c])
    for k in (1, 3):
        y = (tr.dailyRank <= k).astype(int)
        out[f"s1_p{k}"] = lgb.LGBMClassifier(**P).fit(tr[c], y).predict_proba(te[c])[:, 1] if y.nunique() > 1 else 0.0
    return out


def add_standing(d):
    for f in ("s1_r", "s1_p1", "s1_p3"):
        for g in ("day", "week", "mon"):
            d[f"{f}_{g}"] = d.groupby(g)[f].rank(pct=True)
    d["s1_day_max_gap"] = d.s1_r - d.groupby("day").s1_r.transform("max")
    d["s1_week_n"] = d.groupby("week").id.transform("count")
    return d


def one_fold(args):
    m, tr, te = args
    tr, te = M.add_fold_feats(tr, te)
    c = M.cols(tr, SRC)
    # out-of-fold stage 1 on training months
    oof = []
    for mm in sorted(tr.mon.unique()):
        a, b = tr[tr.mon != mm], tr[tr.mon == mm]
        if len(a) > 200:
            oof.append(stage1(a, b, c))
    tr2 = tr.join(pd.concat(oof), how="inner")
    te2 = te.join(stage1(tr, te, c))
    tr2, te2 = add_standing(tr2.copy()), add_standing(te2.copy())
    s = [x for x in tr2.columns if x.startswith("s1_")]
    res = te2[["id", "day", "week", "mon", "dailyRank", "weeklyRank", "monthlyRank", "votes"]].copy()
    for per, col in (("week", "weeklyRank"), ("mon", "monthlyRank")):
        for k in KS:
            y = (tr2[col] <= k).astype(int)
            res[f"stack|{per}{k}"] = lgb.LGBMClassifier(**P).fit(tr2[c + s], y).predict_proba(te2[c + s])[:, 1]
            y = (tr[col] <= k).astype(int)
            res[f"direct|{per}{k}"] = lgb.LGBMClassifier(**P).fit(tr[c], y).predict_proba(te[c])[:, 1]
    res["s1_r"] = te2.s1_r
    print(m, flush=True)
    return res


def main():
    df = RN.load_llm(F.build()); df = df[~df.known]
    folds = list(RN.folds(df, MONTHS))
    with mp.get_context("fork").Pool(min(len(folds), os.cpu_count())) as pool:
        T = pd.concat(pool.map(one_fold, folds))
    T["day"] = T.day.astype(str)
    old = pd.read_csv("results/predictions.csv", usecols=["id", "pred", "pred_week_model", "pred_month_model"])
    T = T.merge(old.assign(id=old.id.astype(str)), on="id", how="left")
    rows = []
    for name, f in [("current (day model)", lambda per, k: "pred"),
                    ("current (week/month model)", lambda per, k: "pred_week_model" if per == "week" else "pred_month_model"),
                    ("predicted votes only", lambda per, k: "s1_r"),
                    ("per-k classifier", lambda per, k: f"direct|{per}{k}"),
                    ("per-k + stage 1 (size of win)", lambda per, k: f"stack|{per}{k}")]:
        r = {"model": name}
        for per, col in (("week", "weeklyRank"), ("mon", "monthlyRank")):
            for k in KS:
                r[f"{per}@{k}"] = round(100 * M.recall_at(T, per, col, k, f(per, k))[0])
        rows.append(r)
    out = pd.DataFrame(rows)
    out.to_csv("results/sizewin.csv", index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
