"""Honesty check of the launch model's backtest (ctrl.py `all`, the 66.7 / 73.5 / 81.0 baseline): inputs whose values
for past launches were read after launch day are dropped, and the model is rescored on the same folds (rolling monthly,
5 seeds, ctrl.py's LightGBM). Leak groups, dropped cumulatively:
  followers   every follower count (makers', hunter's, company's; PH and X) and inputs derived from them (day ranks,
              line-up percentiles / gaps): PH counts come from data/days/ re-read after launch, X counts from later fetches
  follows     fol_ (who follows the team: follows are undated, read now), seg_ (built from follows)
  promo       promo_ (pre-launch posts are dated, but their reaction / reply counts were read at fetch time)
  x_profile   the rest of x_ (verified, bio, account fields read at fetch time)
Prints every dropped column. Daily top 3/5/10 per variant, paired bootstrap over days vs `all` (10,000).
usage: python honest.py -> results/honest.json, results/honest_preds.parquet"""
import json, multiprocessing as mp, os
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd
import model as M, run as RN
from buildcache import build_cached
from ctrl import MONTHS, fit

STEPS = [("followers", lambda c: "follower" in c),
         ("follows", lambda c: c.startswith(("fol_", "seg_")) or "_fol_" in c or c.endswith("_fol")),
         ("promo", lambda c: c.startswith("promo_") or "promo" in c),
         ("x_profile", lambda c: c.startswith("x_") or "_x_" in c)]


def variants(cols):
    V, drop = {"all": cols}, set()
    for name, f in STEPS:
        drop |= {c for c in cols if f(c)}
        V[f"- {name}" if name == "followers" else f"- ... {name}"] = [c for c in cols if c not in drop]
    return V


def job(a):
    m, tr, te, seed = a
    tr, te = M.add_fold_feats(tr, te)
    cols = M.cols(tr, M.LIVE_SOURCES + M.PAGE_SOURCES)
    V = variants(cols)
    out = {"id": te.id.values, "seed": seed}
    for k, c in V.items():
        out[k] = fit(tr, te, c, seed)
    return pd.DataFrame(out), {k: sorted(set(cols) - set(c)) for k, c in V.items()}


def per_day(A, col, k):
    return pd.Series({d: len(set(g.nlargest(k, col).id) & set(g[g.dailyRank <= k].id)) / k for d, g in A.groupby("day") if (g.dailyRank <= k).sum() == k})


def main():
    df = build_cached(); df = df[~df.known].copy()
    jobs = [(m, tr, te, s) for m, tr, te in RN.folds(df, MONTHS) for s in range(5)]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        out = pool.map(job, jobs)
    P = pd.concat([o[0] for o in out]); dropped = out[-1][1]
    V = [c for c in P.columns if c not in ("id", "seed")]
    A = P.groupby("id")[V].mean().reset_index().merge(df[["id", "day", "dailyRank", "logv"]], on="id")
    A = A[A.dailyRank.notna()]
    A.to_parquet("results/honest_preds.parquet")
    rng = np.random.default_rng(0); res = {"launches": len(A), "days": int(A.day.nunique()), "dropped_columns": dropped}
    for win, lo in (("May-Oct", "2026-05"), ("Jul-Oct", "2026-07"), ("all months", "0")):
        U = A[A.day >= lo]; r = {}
        for k in (3, 5, 10):
            base = per_day(U, "all", k); line = {"all": round(100 * float(base.mean()), 1)}
            for v in V[1:]:
                cur = per_day(U, v, k); d = (cur - base).dropna().values
                bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(10000)]
                line[v] = [round(100 * float(cur.mean()), 1), round(100 * float(d.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])]]
            r[f"top{k}"] = line
        res[win] = r
    json.dump(res, open("results/honest.json", "w"), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "dropped_columns"}, indent=1))
    print(json.dumps({k: len(v) for k, v in dropped.items()}))


if __name__ == "__main__":
    main()
