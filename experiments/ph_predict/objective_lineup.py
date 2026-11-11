"""Two 00:05 hypotheses on the honest launch-model setup (orchestrator 23:40Z Nov 11). Runs on the pipeline VM (feature
cache), read-only for the pipeline. Same folds (Mar-Oct month-forward), 5 seeds, honest columns (honest.honest_cols), E5's
ctrl.fit settings for the regression; every variant gets the same columns.
Prior runs (pre-honest feature set): rank_launch.py (LambdaRank +0.6 top 3, within noise), dayexp.py (clf3/clf5/rank/
blends within +-0.4 of regression), ctx_features.py (within-day percentile / gap features), day_strength.py.

1. Objective / ensemble
   reg        LightGBM regression on log votes (E5 ctrl.fit) - the reference
   lr_ndcg    LambdaRank within day, graded relevance top3=4, 4-5=3, 6-10=2, 11-20=1, else 0 (ndcg@3,5,10)
   lr_top3    LambdaRank with a steep gain on the top 3 (label_gain 0,1,3,7,31)
   clf3 / clf10  binary "finished top 3" / "top 10", ranked by probability
   ridge      ridge on standardized honest columns (NaN -> train median)
   avg3       rank average (within day) of reg + lr_ndcg + ridge
2. Line-up competition at 00:05 (same day's line-up only; embeddings data/emb.npz, unit length, product text)
   lu_n_topic     launches that day sharing the launch's first topic
   lu_sim_max / lu_sim_mean   max / mean cosine similarity to the day's other launches
   in-model   reg + those three as extra inputs
   stage2     ridge month-forward on the out-of-fold reg score + [score - day max, sum of the day's top-5 scores,
              lu_n_topic, lu_sim_max, lu_sim_mean, dup_higher (a launch with a higher score that day at cosine >= 0.9)]
Output: results/objective_lineup_preds.parquet (per launch: every variant's score, day, dailyRank)
usage (VM, from ph_predict): PYTHONPATH=~/w/mk python3 objective_lineup.py"""
import json, multiprocessing as mp, os
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd, lightgbm as lgb
import model as M, run as RN
from buildcache import build_cached
from ctrl import MONTHS, fit
from honest import honest_cols

LU = ["lu_n_topic", "lu_sim_max", "lu_sim_mean"]


def lineup(df):
    Z = np.load(os.path.join("data", "emb.npz"), allow_pickle=True)
    li = {str(x): k for k, x in enumerate(Z["launch_ids"])}; E = Z["launch"]
    out = {}
    for d, g in df.groupby("day"):
        ids = g.id.astype(str).tolist(); ft = [t[0] if len(t) else "" for t in g.topics]
        ix = [li.get(i) for i in ids]
        for j, i in enumerate(ids):
            same = sum(1 for k, t in enumerate(ft) if k != j and t and t == ft[j])
            if ix[j] is None:
                out[i] = (same, np.nan, np.nan); continue
            others = [E[ix[k]] for k in range(len(ids)) if k != j and ix[k] is not None]
            s = np.array(others) @ E[ix[j]] if others else np.array([np.nan])
            out[i] = (same, float(np.nanmax(s)), float(np.nanmean(s)))
    df = df.copy()
    for n, c in enumerate(LU):
        df[c] = [out.get(str(i), (np.nan,) * 3)[n] for i in df.id]
    return df


def rel(r):
    return np.select([r <= 3, r <= 5, r <= 10, r <= 20], [4, 3, 2, 1], 0)


DF = {}


def job(a):
    m, seed = a
    df = DF["df"]
    tr, te = df[df.mon < m], df[df.mon == m]
    tr, te = M.add_fold_feats(tr, te)
    cols = honest_cols(M.cols(tr, M.LIVE_SOURCES + M.PAGE_SOURCES))
    out = {"id": te.id.values, "seed": seed, "reg": fit(tr, te, cols, seed), "reg_lu": fit(tr, te, cols + LU, seed)}
    P = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
             colsample_bytree=0.5, reg_lambda=1.0, random_state=seed, verbose=-1, n_jobs=1)
    trs = tr.sort_values("day"); grp = trs.groupby("day", sort=False).size().values; y = rel(trs.dailyRank.fillna(99).values)
    out["lr_ndcg"] = lgb.LGBMRanker(objective="lambdarank", eval_at=[3, 5, 10], **P).fit(trs[cols], y, group=grp).predict(te[cols])
    out["lr_top3"] = lgb.LGBMRanker(objective="lambdarank", label_gain=[0, 1, 3, 7, 31], **P).fit(trs[cols], y, group=grp).predict(te[cols])
    for k in (3, 10):
        out[f"clf{k}"] = lgb.LGBMClassifier(**P).fit(tr[cols], (tr.dailyRank <= k).astype(int)).predict_proba(te[cols])[:, 1]
    from sklearn.linear_model import Ridge
    med = tr[cols].median().fillna(0.0)   # columns empty in the training months -> 0
    Xtr = tr[cols].astype(float).fillna(med); Xte = te[cols].astype(float).fillna(med)
    mu = Xtr.mean(); sd = Xtr.std().fillna(0.0) + 1e-9
    out["ridge"] = Ridge(alpha=10.0).fit(((Xtr - mu) / sd).fillna(0.0), tr.logv).predict(((Xte - mu) / sd).fillna(0.0))
    return pd.DataFrame(out)


def main():
    df = build_cached(); df = df[~df.known].copy(); df["id"] = df.id.astype(str)
    if "mon" not in df:
        df["mon"] = df.day.str[:7]
    df = lineup(df); DF["df"] = df
    jobs = [(m, s) for m in MONTHS for s in range(5) if len(df[df.mon < m]) > 200 and len(df[df.mon == m])]
    with mp.get_context("fork").Pool(int(os.environ.get("PROCS", "3"))) as pool:
        P = pd.concat(pool.map(job, jobs))
    V = [c for c in P.columns if c not in ("id", "seed")]
    A = P.groupby("id")[V].mean().reset_index().merge(df[["id", "day", "mon", "dailyRank", "logv"] + LU], on="id")
    A.to_parquet("results/objective_lineup_preds.parquet")
    print(json.dumps({"launches": int(len(A)), "days": int(A.day.nunique()), "variants": V}))


if __name__ == "__main__":
    main()
