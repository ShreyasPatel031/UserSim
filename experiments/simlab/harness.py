"""Test harness: score any experiment against the same baseline, on launches the model never trained on.

Baseline = the best pre-launch model so far (LightGBM on log votes, all sources), rolling by month: each month is
predicted by a model trained only on earlier months. Its predictions are cached until the inputs change.
An experiment adds a score per launch and is tested two ways, both out of sample:
  blend     within-day standing of baseline + w x within-day standing of the experiment's score; w chosen on the
            other weeks (leave-one-week-out), so it works for scores that exist only for a few weeks
  residual  does the score explain what the baseline gets wrong (within-day Spearman with real-minus-predicted
            standing; bootstrap 95% interval over days)
Every run is logged to registry.jsonl with its scores, interval, launch count and the experiment's undated inputs.
Lists scored: day top 3 / 5 / 10 (PH dailyRank); week/month are reported when the window covers whole weeks."""
import datetime as dt, json, os, subprocess, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
PH = os.path.join(os.path.dirname(HERE), "ph_predict")
sys.path.insert(0, PH)
CACHE = os.path.join(HERE, "cache")
MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
BASE_SOURCES = ["fol", "seg", "promo", "rec", "busy"]   # added to model.SOURCES
KS = (3, 5, 10)


def _fold(a):
    import model as M
    m, tr, te = a
    tr, te = M.add_fold_feats(tr, te)
    out = te[["id", "day", "week", "mon", "dailyRank", "weeklyRank", "monthlyRank", "votes"]].copy()
    out["base"] = M.fit_predict(tr, te, M.SOURCES + BASE_SOURCES)[0]
    return out


def baseline():
    """Out-of-sample baseline predictions for every launch Mar–Oct (cached against the input build)."""
    os.environ.setdefault("LGB_THREADS", "1")
    cwd = os.getcwd(); os.chdir(PH)
    try:
        import multiprocessing as mp
        import run as RN
        from buildcache import build_cached
        df = build_cached(); df = df[~df.known]
        stamp = os.path.getmtime(os.path.join(PH, "data", "build_cache.pkl"))
        path = os.path.join(CACHE, "baseline.parquet")
        if os.path.exists(path) and os.path.getmtime(path) > stamp:
            return pd.read_parquet(path)
        with mp.get_context("fork").Pool(os.cpu_count()) as pool:
            B = pd.concat(pool.map(_fold, list(RN.folds(df, MONTHS))))
    finally:
        os.chdir(cwd)
    os.makedirs(CACHE, exist_ok=True); B["id"] = B.id.astype(str); B.to_parquet(path)
    return B


def recall(T, score, group="day", col="dailyRank", k=5, per_list=False):
    """Mean over lists of |predicted top-k & real top-k| / k (vectorised; random tie-break)."""
    rng = np.random.default_rng(1)
    s = pd.Series(T[score].fillna(-1e9).values + rng.random(len(T)) * 1e-9, index=T.index)
    g = T[group]
    rs = s.groupby(g).rank(ascending=False, method="first")
    rt = T[col].groupby(g).rank(method="first")
    n = g.map(g.value_counts())
    ok = n >= k
    if group == "week":
        ok &= g.map(T.groupby(group).day.nunique()) >= 7
    hits = ((rs <= k) & (rt <= k) & ok).groupby(g).sum()[ok.groupby(g).any()] / k
    return list(hits.values) if per_list else (float(hits.mean()) if len(hits) else np.nan)


def ci(vals, n=2000):
    if len(vals) < 2:
        return [np.nan, np.nan]
    b = np.random.default_rng(0).choice(vals, (n, len(vals))).mean(1)
    return [float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))]


def blend(T, col, grid=(0, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2, 3)):
    """Leave-one-week-out choice of the weight on the experiment's within-day standing."""
    T = T.copy()
    T["pb"] = T.groupby("day").base.rank(pct=True); T["px"] = T.groupby("day")[col].rank(pct=True).fillna(0.5)
    out = pd.Series(index=T.index, dtype=float); ws = []
    for w0 in sorted(T.week.unique()):
        tr, te = T[T.week != w0], T[T.week == w0]
        best = max(grid, key=lambda w: np.mean([recall(tr.assign(s=tr.pb + w * tr.px), "s", k=k) for k in KS]))
        out[te.index] = te.pb + best * te.px; ws.append(best)
    return out, ws


def residual(T, col):
    T = T.copy()
    T["res"] = T.groupby("day").dailyRank.rank(pct=True, ascending=False) - T.groupby("day").base.rank(pct=True)
    rs = np.array([spearmanr(g[col], g.res)[0] for _, g in T.groupby("day") if g[col].nunique() > 1 and len(g) > 5])
    rs = rs[~np.isnan(rs)]
    return float(rs.mean()) if len(rs) else np.nan, ci(list(rs))


def evaluate(name, scores, undated=(), notes=""):
    """scores: DataFrame with `id` and one or more score columns (higher = more likely to rank high)."""
    B = baseline()
    scores = scores.assign(id=scores.id.astype(str))
    T = B.merge(scores, on="id", how="inner")
    T = T[T.groupby("day").id.transform("count") >= 5]
    rows = []
    for k in KS:
        v = recall(T, "base", k=k, per_list=True)
        rows.append({"score": "baseline", "list": f"day@{k}", "recall": np.mean(v), "ci": ci(v)})
    res = {}
    for col in [c for c in scores.columns if c != "id"]:
        T["blend"], ws = blend(T, col)
        for k in KS:
            v = recall(T, col, k=k, per_list=True)
            rows.append({"score": f"{col} alone", "list": f"day@{k}", "recall": np.mean(v), "ci": ci(v)})
            v = recall(T, "blend", k=k, per_list=True)
            rows.append({"score": f"baseline + {col}", "list": f"day@{k}", "recall": np.mean(v), "ci": ci(v)})
        r, rci = residual(T, col)
        res[col] = {"rho_vs_error": r, "ci": rci, "weights": ws}
    R = pd.DataFrame(rows)
    tab = R.pivot_table(index="score", columns="list", values="recall", sort=False).mul(100).round(1)
    rec = {"experiment": name, "time": dt.datetime.utcnow().isoformat(timespec="seconds"),
           "git": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=HERE).stdout.strip(),
           "launches": int(len(T)), "days": int(T.day.nunique()), "window": [T.day.min(), T.day.max()],
           "table": tab.reset_index().to_dict("records"), "residual": res, "undated": list(undated), "notes": notes}
    with open(os.path.join(HERE, "registry.jsonl"), "a") as f:
        f.write(json.dumps(rec, default=float) + "\n")
    print(f"{name}: {len(T)} launches, {T.day.nunique()} days ({T.day.min()} to {T.day.max()})")
    print(tab.to_string())
    for c, v in res.items():
        print(f"residual {c}: rho {v['rho_vs_error']:.3f}  CI {v['ci'][0]:.3f} to {v['ci'][1]:.3f}  weights {sorted(set(v['weights']))}")
    return rec
