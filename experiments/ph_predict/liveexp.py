"""The backtest under live conditions. At forecast time some inputs do not exist yet for today's launches (they are
computed offline, or come from pages read after the launch): measured on Oct 25-28, these are empty for every live row.
  full        backtest as before (optimistic: test rows have every input)
  live        same model, test rows with those inputs blanked (what the daily forecast really gets)
  drop        trained without those inputs (a model built for launch time)
  drop+<src>  launch-time model plus one source, i.e. what computing that source at forecast time would buy
Rolling monthly Mar-Oct, 5 seeds.  usage: python liveexp.py -> results/liveexp.csv"""
import multiprocessing as mp, os
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd
import model as M, run as RN
from buildcache import build_cached

BASE = M.SOURCES + ["fol", "seg", "promo", "rec", "busy"]
LIVE_EMPTY = ["cm", "busy", "fol", "seg", "promo", "rec", "hn"]       # measured: 100% empty on live rows
MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]


def blank(te, srcs):
    te = te.copy()
    for c in M.cols(te, srcs):
        te[c] = np.nan
    return te


def job(a):
    m, tr, te, seed = a
    tr, te = M.add_fold_feats(tr, te)
    drop = [s for s in BASE if s not in LIVE_EMPTY]
    te_live = blank(te, LIVE_EMPTY)
    out = {"id": te.id.values, "seed": seed}
    out["full"] = M.fit_predict(tr, te, BASE, seed=seed)[0]
    out["live"] = M.fit_predict(tr, te_live, BASE, seed=seed)[0]
    out["drop"] = M.fit_predict(tr, te_live, drop, seed=seed)[0]
    for s in LIVE_EMPTY:
        out[f"drop+{s}"] = M.fit_predict(tr, blank(te, [x for x in LIVE_EMPTY if x != s]), drop + [s], seed=seed)[0]
    on = ["seg", "fol", "promo", "busy"]
    out["drop+seg+fol+promo+busy"] = M.fit_predict(tr, blank(te, [x for x in LIVE_EMPTY if x not in on]), drop + on, seed=seed)[0]
    out["live_sources_only_daily"] = M.fit_predict(tr, te_live, M.SOURCES, seed=seed)[0]   # what forecast.py trains on
    return pd.DataFrame(out)


def main():
    df = build_cached(); df = df[~df.known].copy()
    jobs = [(m, tr, te, s) for m, tr, te in RN.folds(df, MONTHS) for s in range(5)]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        P = pd.concat(pool.map(job, jobs))
    T = df[["id", "day", "dailyRank"]].merge(P, on="id").dropna(subset=["dailyRank"])
    rows = []
    for v in [c for c in P.columns if c not in ("id", "seed")]:
        for s, g in T.groupby("seed"):
            for k in (3, 5, 10):
                rows.append({"variant": v, "seed": s, "k": k, "recall": np.mean(M.recall_at(g, "day", "dailyRank", k, v, per_list=True))})
    R = pd.DataFrame(rows).groupby(["variant", "k"]).recall.mean().mul(100).round(1).unstack()
    print(R.sort_values(3, ascending=False).to_string())
    R.to_csv("results/liveexp.csv")


if __name__ == "__main__":
    main()
