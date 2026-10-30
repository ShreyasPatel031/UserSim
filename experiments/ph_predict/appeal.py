"""Visibility vs appeal (Hogg & Lerman, Social Dynamics of Digg, arXiv 1202.0031): votes = how many saw it x how many of
those liked it. Here reach (the fixed-inputs prediction from ctrl.py, out of sample) stands in for visibility, and
appeal = real log votes minus that. A page-only model is trained to predict appeal directly (rolling monthly, 5 seeds),
so the page can't lean on reach. Compared with the page lift from ctrl.py on the same launches:
  correlation with real appeal within day (95% interval) and accuracy on same-day pairs with matched reach.
usage: python appeal.py -> results/appeal.json"""
import json, multiprocessing as mp, os
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd, lightgbm as lgb
from scipy.stats import spearmanr
from buildcache import build_cached
from ctrl import group
import model as M

MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]


def job(a):
    m, tr, te, cols, seed = a
    mdl = lgb.LGBMRegressor(n_estimators=500, learning_rate=0.02, num_leaves=15, min_child_samples=40, subsample=0.8, subsample_freq=1,
                            colsample_bytree=0.5, reg_lambda=2.0, random_state=seed, verbose=-1, n_jobs=1)
    return pd.DataFrame({"id": te.id.values, "seed": seed, "appeal_pred": mdl.fit(tr[cols], tr.appeal).predict(te[cols])})


def main():
    df = build_cached(); P = pd.read_parquet("results/ctrl_preds.parquet")
    df = df.drop(columns=["logv"], errors="ignore").merge(P[["id", "logv", "fixed", "fixed+page"]], on="id")
    df["appeal"] = df.logv - df.fixed
    cols = [c for c in M.cols(df, M.LIVE_SOURCES + M.PAGE_SOURCES + ["upw"]) if group(c) == "page" or c.startswith("upw_")]
    jobs = [(m, df[df.mon < m], df[df.mon == m], cols, s) for m in MONTHS for s in range(5)]
    with mp.get_context("fork").Pool(os.cpu_count() // 2) as pool:
        A = pd.concat(pool.map(job, jobs)).groupby("id").appeal_pred.mean().reset_index()
    A = A.merge(df[["id", "day", "logv", "fixed", "fixed+page", "appeal"]], on="id"); A["page_lift"] = A["fixed+page"] - A.fixed
    res = {"page_inputs": len(cols)}; rng = np.random.default_rng(0)
    for col in ("appeal_pred", "page_lift"):
        per = np.array([spearmanr(g[col], g.appeal).correlation for _, g in A.groupby("day") if len(g) >= 8])
        bs = [rng.choice(per, len(per)).mean() for _ in range(2000)]
        hits = []
        for _, g in A.groupby("day"):
            g = g.to_dict("records")
            hits += [(a[col] > b[col]) == (a["logv"] > b["logv"]) for i, a in enumerate(g) for b in g[i + 1:]
                     if abs(a["fixed"] - b["fixed"]) < 0.15 and a["logv"] != b["logv"]]
        res[col] = {"corr_with_appeal": round(float(per.mean()), 3), "ci95": [round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3)],
                    "matched_pairs_acc": round(100 * float(np.mean(hits)), 1), "pairs": len(hits)}
    json.dump(res, open("results/appeal.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
