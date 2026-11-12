"""Training window of the 00:05 launch model (orchestrator 02:40Z Nov 12). Runs on the pipeline VM (feature cache),
read-only for the pipeline. Honest setup: build_cached, honest.honest_cols over M.LIVE_SOURCES + M.PAGE_SOURCES,
E5's ctrl.fit settings (LightGBM regression on log votes), 5 seeds, test months Mar-Oct (ctrl.MONTHS).
Variants (every one scored on the same test days, same columns):
  ref        month-forward expanding window (train on every month before the test month) - the reference
  daily      expanding window refit every test day (train on every day before it) - what the deployed pipeline does
  roll60 / roll90 / roll120   month-forward, only the last N days before the test month's first day
  hl30 / hl60 / hl90          month-forward expanding, sample weight 0.5 ** (age in days / half-life), age vs the test
                              month's first day
  dow        ref + day-of-week (0-6) and weekend flag as inputs
  split      separate weekday and weekend models (each trained on its own days only)
Output: results/training_window_preds.parquet (per launch: every variant's mean score over seeds, day, dailyRank)
usage (VM, from ph_predict): PYTHONPATH=~/w/mk PROCS=3 python3 training_window.py [--variants a,b]"""
import json, multiprocessing as mp, os, sys, time
os.environ.setdefault("LGB_THREADS", "1")
import numpy as np, pandas as pd, lightgbm as lgb
import model as M
from buildcache import build_cached
from ctrl import MONTHS as _M
MONTHS = list(_M) + ["2026-11"]   # + November (partial: days with final ranks in the cache), where the live line struggles
from honest import honest_cols

DF = {}
P0 = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
          colsample_bytree=0.5, reg_lambda=1.0, verbose=-1, n_jobs=1)


def fitw(tr, te, cols, seed, w=None):
    return lgb.LGBMRegressor(random_state=seed, **P0).fit(tr[cols], tr.logv, sample_weight=w).predict(te[cols])


def prep(tr, te):
    tr, te = M.add_fold_feats(tr, te)
    return tr, te, honest_cols(M.cols(tr, M.LIVE_SOURCES + M.PAGE_SOURCES))


def live_cols(tr):
    return M.cols(tr, M.LIVE_SOURCES)


def month_job(a):
    m, seed, variants = a
    df = DF["df"]; start = pd.Timestamp(m + "-01")
    tr0, te0 = df[df.mon < m], df[df.mon == m]
    tr, te, cols = prep(tr0, te0)
    out = {"id": te.id.values, "seed": seed}
    age = (start - pd.to_datetime(tr.day)).dt.days.values
    if "ref" in variants:
        out["ref"] = fitw(tr, te, cols, seed)
    # orchestrator 03:35Z Nov 12: the deployed feature set (M.LIVE_SOURCES, follower / follow-list / promo inputs kept, no
    # page sources) and the honest filter without the page sources, same params (LIVE_PARAMS == ctrl.fit settings)
    if "live_month" in variants:
        out["live_month"] = fitw(tr, te, live_cols(tr), seed)
    if "honest_nopage_month" in variants:
        out["honest_nopage_month"] = fitw(tr, te, honest_cols(live_cols(tr)), seed)
    for n in (60, 90, 120):
        if f"roll{n}" in variants:
            t2, e2, c2 = prep(tr0[pd.to_datetime(tr0.day) >= start - pd.Timedelta(days=n)], te0)
            out[f"roll{n}"] = pd.Series(fitw(t2, e2, c2, seed), index=e2.index).reindex(te.index).values
    for hl in (30, 60, 90):
        if f"hl{hl}" in variants:
            out[f"hl{hl}"] = fitw(tr, te, cols, seed, 0.5 ** (age / hl))
    if "dow" in variants:
        for d in (tr, te):
            d["dow"] = pd.to_datetime(d.day).dt.dayofweek; d["wkend"] = (d.dow >= 5).astype(int)
        out["dow"] = fitw(tr, te, cols + [c for c in ("dow", "wkend") if c not in cols], seed)
    if "split" in variants:
        s = np.full(len(te), np.nan); wk_tr = pd.to_datetime(tr.day).dt.dayofweek >= 5; wk_te = (pd.to_datetime(te.day).dt.dayofweek >= 5).values
        for flag in (False, True):
            if (wk_te == flag).any():
                s[wk_te == flag] = fitw(tr[wk_tr == flag], te[wk_te == flag], cols, seed)
        out["split"] = s
    return pd.DataFrame(out)


def day_job(a):
    d, seed, dv = a
    df = DF["df"]
    tr, te, cols = prep(df[df.day < d], df[df.day == d])
    out = {"id": te.id.values, "seed": seed}
    if "daily" in dv:
        out["daily"] = fitw(tr, te, cols, seed)
    if "live_daily" in dv:   # the deployed configuration: LIVE_SOURCES, daily expanding refit
        out["live_daily"] = fitw(tr, te, live_cols(tr), seed)
    return pd.DataFrame(out)


def main():
    t = time.time()
    V = ["ref", "roll60", "roll90", "roll120", "hl30", "hl60", "hl90", "dow", "split", "daily"]
    for a in sys.argv[1:]:
        if a.startswith("--variants"):
            V = sys.argv[sys.argv.index(a) + 1].split(",")
    df = build_cached(); df = df[~df.known].copy(); df["id"] = df.id.astype(str)
    if "mon" not in df:
        df["mon"] = df.day.str[:7]
    DF["df"] = df
    print(json.dumps({"rows": int(len(df)), "first_day": df.day.min(), "last_day": df.day.max(), "variants": V}), flush=True)
    dv = [v for v in V if v in ("daily", "live_daily")]
    mv = [v for v in V if v not in dv]
    jobs = [(m, s, mv) for m in MONTHS for s in range(5) if len(df[df.mon < m]) > 200 and len(df[df.mon == m])]
    test_days = sorted(df[df.mon.isin([j[0] for j in jobs])].day.unique())
    parts = []
    with mp.get_context("fork").Pool(int(os.environ.get("PROCS", "3"))) as pool:
        if mv:
            P = pd.concat(pool.map(month_job, jobs)); parts.append(P.groupby("id")[mv].mean())
            print("month variants done", round(time.time() - t), "s", flush=True)
        if dv:
            D = pd.concat(pool.map(day_job, [(d, s, dv) for d in test_days for s in range(5)], chunksize=4))
            parts.append(D.groupby("id")[dv].mean())
            print("daily done", round(time.time() - t), "s", flush=True)
    A = pd.concat(parts, axis=1).reset_index().merge(df[["id", "day", "mon", "dailyRank", "logv"]], on="id")
    A.to_parquet(os.environ.get("TW_OUT", "results/training_window_preds.parquet"))
    print(json.dumps({"launches": int(len(A)), "days": int(A.day.nunique()), "variants": V, "seconds": round(time.time() - t)}), flush=True)


if __name__ == "__main__":
    main()
