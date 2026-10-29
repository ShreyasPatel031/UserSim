"""Live daily model: remove one input source at a time, and other model settings. Rolling monthly Mar-Oct, 5 seeds,
scored as deployed (5-seed average).  usage: python tune.py -> results/tune.csv"""
import multiprocessing as mp, os
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd, lightgbm as lgb
import model as M, run as RN
from buildcache import build_cached

MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
LIVE = M.LIVE_SOURCES
DEF = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
           colsample_bytree=0.8, reg_lambda=1.0)
SETTINGS = {"slow_800": dict(n_estimators=800, learning_rate=0.015), "leaves7": dict(num_leaves=7), "leaves31": dict(num_leaves=31),
            "minchild50": dict(min_child_samples=50), "col05": dict(colsample_bytree=0.5), "trees250": dict(n_estimators=250),
            "l1": dict(objective="huber", alpha=1.0)}


def fit(tr, te, src, seed, **kw):
    c = M.cols(tr, src)
    m = lgb.LGBMRegressor(**{**DEF, **kw}, random_state=seed, verbose=-1, n_jobs=1)
    return m.fit(tr[c], tr.logv).predict(te[c])


def job(a):
    m, tr, te, seed = a
    tr, te = M.add_fold_feats(tr, te)
    out = {"id": te.id.values, "seed": seed, "live": fit(tr, te, LIVE, seed)}
    if os.environ.get("FULLTEST"):        # the full-context Gemini judgement (llm_full) on vs off, live settings
        P = dict(colsample_bytree=0.5)
        out["live"] = fit(tr.drop(columns=["llm_full"]), te.drop(columns=["llm_full"]), LIVE, seed, **P)
        out["live+llm_full"] = fit(tr, te, LIVE, seed, **P)
        out["live-llm_pitch_site_brand+llm_full"] = fit(tr.drop(columns=["llm_pitch", "llm_site", "llm_brand"]),
                                                       te.drop(columns=["llm_pitch", "llm_site", "llm_brand"]), LIVE, seed, **P)
        return pd.DataFrame(out)
    if os.environ.get("COMBOS"):          # e.g. COMBOS="web,dom;web,comp,topic,dom" -> remove those sources together
        for combo in os.environ["COMBOS"].split(";"):
            drop = combo.split(",")
            out["-" + "-".join(drop)] = fit(tr, te, [x for x in LIVE if x not in drop], seed)
            out["-" + "-".join(drop) + " col05"] = fit(tr, te, [x for x in LIVE if x not in drop], seed, colsample_bytree=0.5)
        return pd.DataFrame(out)
    for s in LIVE:
        out[f"-{s}"] = fit(tr, te, [x for x in LIVE if x != s], seed)
    for k, kw in SETTINGS.items():
        out[k] = fit(tr, te, LIVE, seed, **kw)
    return pd.DataFrame(out)


def main():
    df = build_cached(); df = df[~df.known].copy()
    jobs = [(m, tr, te, s) for m, tr, te in RN.folds(df, MONTHS) for s in range(int(os.environ.get("SEED0", 0)), int(os.environ.get("SEED0", 0)) + 5)]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        P = pd.concat(pool.map(job, jobs))
    V = [c for c in P.columns if c not in ("id", "seed")]
    A = P.groupby("id")[V].mean().reset_index().merge(df[["id", "day", "dailyRank"]], on="id").dropna(subset=["dailyRank"])
    R = pd.DataFrame({v: [100 * np.mean(M.recall_at(A, "day", "dailyRank", k, v, per_list=True)) for k in (3, 5, 10)] for v in V},
                     index=["top3", "top5", "top10"]).T.round(1)
    R["sum"] = R.sum(axis=1).round(1)
    A["mon"] = A.day.str[:7]
    if os.environ.get("COMBOS") or os.environ.get("FULLTEST"):   # month by month, top 3, each variant vs live
        Mo = pd.DataFrame({v: {m: 100 * np.mean(M.recall_at(g, "day", "dailyRank", 3, v, per_list=True)) for m, g in A.groupby("mon")} for v in V}).round(1)
        print(Mo.to_string()); print("months better / worse than live:", {v: f"{int((Mo[v] > Mo.live).sum())}/{int((Mo[v] < Mo.live).sum())}" for v in V if v != "live"})
    print(R.sort_values("sum", ascending=False).to_string()); R.to_csv("results/tune" + ("_combos" if os.environ.get("COMBOS") else "") + ".csv")


if __name__ == "__main__":
    main()
