"""Robustness of a source's daily/weekly/monthly gain: current model vs + source, over 5 seeds of the list classifiers,
per month and per week (each fold x seed x variant in parallel).  usage: python robust_src.py aga"""
import multiprocessing as mp, os, sys
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd
import model as M, run as RN
from buildcache import build_cached

BASE = M.SOURCES + ["fol", "seg", "promo", "rec", "busy"]


def job(a):
    m, tr, te, seed, name, src = a
    os.environ["LIST_SEED"] = str(seed)
    tr, te = M.add_fold_feats(tr, te); te = te.copy()
    te["d"] = M.fit_predict(tr, te, src, seed=seed)[0]
    M.SOURCES = src
    te["w"] = M.fit_list_clf(tr, te, "week", "weeklyRank", 10)
    te["m"] = M.fit_list_clf(tr, te, "mon", "monthlyRank", 20)
    rows = []
    for k in (3, 5, 10):
        for per, col, s in (("day", "dailyRank", "d"), ("week", "weeklyRank", "w"), ("mon", "monthlyRank", "m")):
            for key, v in zip(sorted(te[per].unique()), M.recall_at(te, per, col, k, s, per_list=True)):
                rows.append({"variant": name, "seed": seed, "list": f"{per}@{k}", "key": key, "recall": v})
    return rows


def main(srcs):
    df = build_cached(); df = df[~df.known]
    folds = list(RN.folds(df, ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]))
    vs = [("current", BASE)] + [(f"+ {s}", BASE + s.split("+")) for s in srcs]   # "aud+aga" = both added
    jobs = [(m, tr, te, s, n, v) for (m, tr, te) in folds for s in range(5) for n, v in vs]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        R = pd.DataFrame([r for rows in pool.map(job, jobs) for r in rows])
    P = R.groupby(["list", "variant"]).recall.mean().unstack().mul(100).round(1)
    # paired difference per list (week / month), averaged over seeds; share of lists where the source is better
    D = R.groupby(["list", "key", "variant"]).recall.mean().unstack()
    for s in srcs:
        d = (D[f"+ {s}"] - D["current"])
        P[f"gain {s}"] = d.groupby(level=0).mean().mul(100).round(1)
        P[f"better/worse {s}"] = d.groupby(level=0).apply(lambda x: f"{(x > 0).sum()}/{(x < 0).sum()}")
    print(P.to_string())
    P.to_csv(f"results/robust_{'_'.join(srcs)}.csv")


if __name__ == "__main__":
    main(sys.argv[1:])
