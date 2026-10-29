"""Daily-list model variants (same inputs as the daily forecast), rolling monthly Mar-Oct, 5 seeds:
  reg       current: LightGBM regression on log votes
  clf3/5    classifier "finished in the day's top 3 / 5", with each launch's standing within its day on key signals
  rank      LambdaRank within each day
  wreg      regression with the day's top 10 weighted up (the list is what we are scored on)
  blend_*   average of within-day rank percentiles of two scores
usage: python dayexp.py  -> results/dayexp.csv"""
import multiprocessing as mp, os, sys
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd, lightgbm as lgb
import model as M, run as RN
from buildcache import build_cached

BASE = M.LIVE_SOURCES if os.environ.get("LIVE") else M.SOURCES + ["fol", "seg", "promo", "rec", "busy"]
MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
KEYF = ["ph_hunter_followers", "ph_maker_max_followers", "hist_hunter_rel", "hist_maker_rel_max", "x_maker_max_followers",
        "x_company_followers", "llm_brand", "llm_pitch", "ph_n_makers", "txt_ridge", "fol_team", "rec_c30", "cm_pre_users"]


def day_pct(tr, te):
    tr, te = tr.copy(), te.copy()
    for d in (tr, te):
        for f in KEYF:
            if f in d:
                d[f"dp_{f}"] = d.groupby("day")[f].rank(pct=True)
    return tr, te, [f"dp_{f}" for f in KEYF if f in tr]


def gbm(kind, seed, n=400):
    kw = dict(n_estimators=n, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
              colsample_bytree=0.8, random_state=seed, verbose=-1, n_jobs=1)
    return {"reg": lgb.LGBMRegressor, "clf": lgb.LGBMClassifier, "rank": lgb.LGBMRanker}[kind](**kw)


def job(a):
    m, tr, te, seed = a
    tr, te = M.add_fold_feats(tr, te)
    c = M.cols(tr, BASE)
    tr, te, dp = day_pct(tr, te)
    out = {"id": te.id.values, "seed": seed}
    out["reg"] = gbm("reg", seed).fit(tr[c], tr.logv).predict(te[c])
    out["reg_dp"] = gbm("reg", seed).fit(tr[c + dp], tr.logv).predict(te[c + dp])
    w = 1 + 2 * (tr.dailyRank <= 10).values
    out["wreg"] = gbm("reg", seed).fit(tr[c], tr.logv, sample_weight=w).predict(te[c])
    for k in (3, 5):
        out[f"clf{k}"] = gbm("clf", seed).fit(tr[c + dp], (tr.dailyRank <= k).astype(int)).predict_proba(te[c + dp])[:, 1]
    trs = tr.sort_values("day")
    rel = np.clip(11 - trs.dailyRank.fillna(99).values, 0, 10).astype(int)
    out["rank"] = gbm("rank", seed).fit(trs[c + dp], rel, group=trs.groupby("day", sort=False).size().values).predict(te[c + dp])
    return pd.DataFrame(out)


def main():
    df = build_cached(); df = df[~df.known].copy()
    jobs = [(m, tr, te, s) for m, tr, te in RN.folds(df, MONTHS) for s in range(5)]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        P = pd.concat(pool.map(job, jobs))
    V = [c for c in P.columns if c not in ("id", "seed")]
    T = df[["id", "day", "dailyRank", "votes"]].merge(P, on="id")
    for a, b in (("reg", "clf3"), ("reg", "clf5"), ("reg", "rank"), ("reg_dp", "clf3")):
        T[f"blend_{a}_{b}"] = sum(T.groupby(["seed", "day"])[x].rank(pct=True) for x in (a, b))
    V += [c for c in T.columns if c.startswith("blend_")]
    rows = []
    for v in V:
        for s, g in T.groupby("seed"):
            for k in (3, 5, 10):
                vals = M.recall_at(g.dropna(subset=["dailyRank"]), "day", "dailyRank", k, v, per_list=True)
                rows.append({"variant": v, "seed": s, "k": k, "recall": np.mean(vals)})
    R = pd.DataFrame(rows).groupby(["variant", "k"]).recall.agg(["mean", "std"]).mul(100).round(1).unstack()
    print(R.sort_values(("mean", 3), ascending=False).to_string())
    tag = "_live" if os.environ.get("LIVE") else ""
    R.to_csv(f"results/dayexp{tag}.csv"); T.to_parquet(f"results/dayexp{tag}_preds.parquet")
    A = T.groupby(["id", "day", "dailyRank"], as_index=False)[V].mean()     # 5-seed average, as the live forecast does
    print("5-seed average:", {v: [round(100 * np.mean(M.recall_at(A, "day", "dailyRank", k, v, per_list=True)), 1) for k in (3, 5, 10)]
                              for v in ("reg", "clf5", "blend_reg_clf5", "blend_reg_clf3", "blend_reg_rank")})


if __name__ == "__main__":
    main()
