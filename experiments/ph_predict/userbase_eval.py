"""Shared evaluation for new pre-launch launch-level inputs (A1 team history, C1 user base), against the honest model.
1. Gate: per input, within-day Spearman with the honest residual (final log votes minus the honest launch model,
   honest.py column `honest`), over days with >= 5 launches having the input, paired bootstrap over days (10,000).
   Passes when the 95% interval excludes 0.
2. Boards: the honest day-calibrated control (offset Poisson LightGBM, the honest prediction as offset, day terms only:
   weekday, line-up size, the line-up's predicted total, 7-day trailing real and predicted totals ending day-2) vs the
   same model plus the inputs (NaN where missing, plus a has_<block> flag). Rolling monthly (train on earlier months,
   from Apr), 5 seeds. Daily / weekly / monthly top 3/5/10, paired bootstrap over lists, by month.
Inputs: HONEST_PREDS (default results/honest_preds.parquet; columns id, day, honest, logv, dailyRank, weeklyRank,
monthlyRank)."""
import json, os
import numpy as np, pandas as pd
from scipy.stats import spearmanr

RANK = {"day": "dailyRank", "week": "weeklyRank", "mon": "monthlyRank"}
DAY_COLS = ["day_wd", "day_n", "day_lm_sum", "trail_real7", "trail_lm7"]
NEED_H = ["id", "day", "honest", "logv", "dailyRank", "weeklyRank", "monthlyRank"]


def need(df, cols, what):
    miss = [c for c in cols if c not in df.columns]
    if miss:
        raise SystemExit(f"{what}: missing columns {miss}; has {sorted(df.columns)[:30]}")


def honest():
    H = pd.read_parquet(os.environ.get("HONEST_PREDS", "results/honest_preds.parquet"))
    need(H, NEED_H, "honest predictions")
    col = os.environ.get("HONEST_COL", "honest")   # "honest - live set": the live forecast's honest inputs (the reference, 62.7 / 70.4 / 76.6)
    if col != "honest":
        need(H, [col], "honest predictions")
        H = H.drop(columns="honest").rename(columns={col: "honest"})
    H = H[NEED_H].copy(); H["id"] = H.id.astype(str)
    return H.drop_duplicates("id")


def boot(d, rng, n=10000):
    d = np.asarray(d, float); d = d[~np.isnan(d)]
    if len(d) < 2:
        return [round(float(d.mean()), 4) if len(d) else None, None, int(len(d))]
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(n)]
    return [round(float(d.mean()), 4), [round(float(x), 4) for x in np.percentile(bs, [2.5, 97.5])], int(len(d))]


def gate(A, cols, rng, min_n=5, n=10000):
    """Per input: (1) within-day Spearman with the honest residual, on days with >= min_n covered launches, bootstrap
    over days; (2) pooled: Spearman over all covered launches of the input vs the residual minus its day mean, bootstrap
    over days (works for sparse inputs). Passing needs the Holm-corrected bootstrap p < 0.05 across the block's inputs
    (random inputs pass ~1 in 20 uncorrected)."""
    A = A.assign(resid=A.logv - A.honest)
    A["resid_d"] = A.resid - A.groupby("day").resid.transform("mean")
    out, ps = {}, {}
    days = A.day.unique()
    for c in cols:
        per = [spearmanr(g[c], g.resid).correlation for _, g in A[A[c].notna()].groupby("day") if len(g) >= min_n and g[c].nunique() > 1]
        b = boot(per, rng, n)
        C = A[A[c].notna()]; byd = {d: g for d, g in C.groupby("day")}; dl = [d for d in days if d in byd]
        pooled = spearmanr(C[c], C.resid_d).correlation if len(C) > 10 and C[c].nunique() > 1 else np.nan
        bs = []
        if dl and not np.isnan(pooled):
            for _ in range(min(n, 2000)):
                S = pd.concat([byd[d] for d in rng.choice(dl, len(dl))])
                bs.append(spearmanr(S[c], S.resid_d).correlation if S[c].nunique() > 1 else np.nan)
        bs = np.array([x for x in bs if not np.isnan(x)])
        p = float(min(1.0, 2 * min((bs <= 0).mean(), (bs >= 0).mean()))) if len(bs) else 1.0
        out[c] = {"within_day_spearman": b[0], "within_day_ci95": b[1], "days": b[2],
                  "pooled_spearman": None if np.isnan(pooled) else round(float(pooled), 4),
                  "pooled_ci95": [round(float(x), 4) for x in np.percentile(bs, [2.5, 97.5])] if len(bs) else None,
                  "covered_launches": int(len(C)), "coverage": round(float(A[c].notna().mean()), 3), "p_boot": round(p, 4)}
        ps[c] = p
    m = len(ps); order = sorted(ps, key=ps.get); worst = 0.0
    for i, c in enumerate(order):   # Holm step-down
        worst = max(worst, min(1.0, ps[c] * (m - i)))
        out[c]["p_holm"] = round(worst, 4); out[c]["passes"] = bool(worst < 0.05)
    return out


def day_terms(A):
    A = A.copy()
    A["mu0"] = np.expm1(A.honest).clip(lower=0.5); A["y"] = np.expm1(A.logv).clip(lower=0)
    D = A.groupby("day").agg(day_n=("id", "size"), day_lm_sum=("mu0", "sum"), real=("y", "sum")).sort_index()
    D["day_wd"] = pd.to_datetime(D.index).dayofweek
    D["trail_real7"] = D.real.shift(2).rolling(7, min_periods=3).mean()
    D["trail_lm7"] = D.day_lm_sum.shift(2).rolling(7, min_periods=3).mean()
    A = A.merge(D[DAY_COLS], left_on="day", right_index=True)
    A["week"] = pd.to_datetime(A.day).dt.strftime("%G-W%V"); A["mon"] = A.day.str[:7]
    return A


def fit_boards(A, cols, seeds=5, start="2026-05"):
    import lightgbm as lgb
    out = []
    for m in sorted(A.mon.unique()):
        if m < start:
            continue
        tr, te = A[A.mon < m], A[A.mon == m].copy()
        if len(tr) < 200:
            continue
        for name, cs in (("control", DAY_COLS), ("test", DAY_COLS + cols)):
            raw = np.mean([lgb.train({"objective": "poisson", "learning_rate": 0.03, "num_leaves": 7, "min_data_in_leaf": 100,
                                      "bagging_fraction": 0.8, "bagging_freq": 1, "seed": s, "verbose": -1, "num_threads": 8},
                                     lgb.Dataset(tr[cs], tr.y, init_score=np.log(tr.mu0)), num_boost_round=200).predict(te[cs], raw_score=True)
                           for s in range(seeds)], 0)
            te[name] = raw + np.log(te.mu0)
        # linear arm for sparse inputs (the trees need 100 rows a leaf): the control plus a ridge fit of the honest
        # residual on the inputs (NaN -> 0, with the has_ flag), fitted on covered launches of earlier months only
        X = [c for c in cols]
        trc = tr[tr[X[-1]] > 0] if X and X[-1].startswith("has_") else tr
        if len(trc) >= 20:
            Z = np.c_[np.ones(len(trc)), trc[X].fillna(0).values]; mu, sd = Z.mean(0), Z.std(0) + 1e-9; mu[0], sd[0] = 0, 1
            Zs = (Z - mu) / sd; w = np.linalg.solve(Zs.T @ Zs + 5.0 * np.eye(Zs.shape[1]), Zs.T @ (trc.logv - trc.honest).values)
            Zt = (np.c_[np.ones(len(te)), te[X].fillna(0).values] - mu) / sd
            adj = Zt @ w
            if X and X[-1].startswith("has_"):
                adj = np.where(te[X[-1]].values > 0, adj, 0.0)
            te["linear"] = te["control"] + adj
        else:
            te["linear"] = te["control"]
        out.append(te)
    return pd.concat(out)


def per_list(T, col, key, k):
    r = RANK[key]
    return pd.Series({g_: len(set(g.nlargest(k, col).id) & set(g[g[r] <= k].id)) / k for g_, g in T.groupby(key) if (g[r] <= k).sum() == k})


def boards(T, rng):
    res = {}; wk_mon = T.groupby("week").day.min().str[:7]
    for key in ("day", "week", "mon"):
        for k in (3, 5, 10):
            a, b, c = per_list(T, "control", key, k), per_list(T, "test", key, k), per_list(T, "linear", key, k)
            ks = a.index.intersection(b.index); d = (b[ks] - a[ks]) * 100; dl = (c[ks] - a[ks]) * 100
            line = {"control": round(100 * float(a[ks].mean()), 1) if len(ks) else None,
                    "with inputs": round(100 * float(b[ks].mean()), 1) if len(ks) else None, "delta": boot(d.values, rng),
                    "linear": round(100 * float(c[ks].mean()), 1) if len(ks) else None, "delta linear": boot(dl.values, rng)}
            month = pd.Series([wk_mon[x] if key == "week" else str(x)[:7] for x in ks], index=ks)
            line["by month"] = {m: round(float(v), 1) for m, v in d.groupby(month.values).mean().items()} if len(ks) else {}
            res[f"{key} top{k}"] = line
    return res


def evaluate(F, name, cols, out_path):
    """F: id + input columns (NaN where missing). Writes and prints the gate and the board comparison."""
    need(F, ["id"] + cols, name)
    F = F.copy(); F["id"] = F.id.astype(str)
    rng = np.random.default_rng(0)
    A = honest().merge(F[["id"] + cols], on="id", how="left")
    A[f"has_{name}"] = A[cols].notna().any(axis=1).astype(float)
    res = {"name": name, "launches": len(A), "coverage": round(float(A[f"has_{name}"].mean()), 3),
           "coverage_by_month": {m: round(float(v), 3) for m, v in A.groupby(A.day.str[:7])[f"has_{name}"].mean().items()}}
    res["gate"] = gate(A, cols, rng)
    T = fit_boards(day_terms(A), cols + [f"has_{name}"], seeds=int(os.environ.get("SEEDS", "5")))
    res["months_tested"] = sorted(T.mon.unique())
    res["boards"] = boards(T, rng)
    json.dump(res, open(out_path, "w"), indent=1)
    print(json.dumps(res, indent=1))
    return res
