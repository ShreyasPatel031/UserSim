"""Experiment B (orchestrator Nov 11): P(pick L | person p, seen set) proportional to exposure(position of L) x taste(p, L).
Conditional logit within the seen set (the day's final top 20; position = final daily rank bucket: 1, 2-3, 4-5, 6-10,
11-20). Exposure uses final ranks, i.e. outcomes: this decomposes preference given exposure (a validation of the
user sim's taste part), it is not a forecast.
Taste = product-only inputs from it8's base rows (no ties): meaning (embedding vs history centroid), topic, seq_last10,
seq_decay, seq_nn, cat_rate_max, cat_rate_mean, cat_prior, cat_n; z-scored within person-day.
Each pick is one choice from the set. Fit on earlier days, test on later days (forward split at the median day), and
leave-one-day-out. Reported on held-out choices: log-likelihood per choice, Hit@1 / Hit@3 for exposure only, taste only,
exposure + taste; by person type: heavy vs light (log_act_30 above / below the median), tied vs untied (any backed > 0
in the set).
usage: SIMBT=<dir> python exposure_taste.py -> results/exposure_taste.json"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy.optimize import minimize

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
WORK = os.environ["SIMBT"]
TASTE = ["meaning", "topic", "seq_last10", "seq_decay", "seq_nn", "cat_rate_max", "cat_rate_mean", "cat_prior", "cat_n"]
EXPO = ["e_1", "e_2_3", "e_4_5", "e_6_10"]   # baseline bucket 11-20


def build():
    import two_level as T
    from pipeline import warehouse as W
    ok, _ = T._label_maps()
    L = W.query("SELECT CAST(id AS VARCHAR) AS id, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    rk = dict(zip(L.id, L.daily_rank))
    out = []
    for f in sorted(glob.glob(f"{WORK}/rows_tl_cp_unc/X_*.parquet")):
        d = os.path.basename(f)[2:12]
        if not ("2026-10-20" <= d <= "2026-11-08"):
            continue
        X = pd.read_parquet(f, columns=["person", "id", "y", "backed", "log_act_30"] + TASTE); X["id"] = X.id.astype(str)
        X = X[ok(X.person, d)]; X["rank"] = X.id.map(rk); X = X[X["rank"] <= 20]
        if X.id.nunique() < 20:
            continue
        X = X[X.groupby("person").y.transform("sum") > 0].copy(); X["day"] = d; X["g"] = X.person + "|" + d
        g = X.groupby("g")
        for c in TASTE:
            X[c] = ((X[c] - g[c].transform("mean")) / (g[c].transform("std") + 1e-9)).fillna(0)
        X["tied"] = g.backed.transform(lambda s: float((s > 0).any()))
        for nm, (lo, hi) in zip(EXPO, ((1, 1), (2, 3), (4, 5), (6, 10))):
            X[nm] = ((X["rank"] >= lo) & (X["rank"] <= hi)).astype(float)
        out.append(X)
    D = pd.concat(out, ignore_index=True)
    D["heavy"] = (D.groupby("g").log_act_30.transform("first") > D.groupby("g").log_act_30.first().median()).astype(float)
    return D


def nll(beta, X, gidx, y, ng):
    u = X @ beta; u = u - np.max(u)
    e = np.exp(u); den = np.bincount(gidx, weights=e, minlength=ng)
    ll = (y * (u - np.log(den[gidx]))).sum()
    p = e / den[gidx]
    grad = X.T @ (y - p * np.bincount(gidx, weights=y, minlength=ng)[gidx])
    return -ll / y.sum(), -grad / y.sum()


def fit(D, cols):
    gi = pd.factorize(D.g)[0]
    r = minimize(nll, np.zeros(len(cols)), args=(D[cols].values, gi, D.y.values.astype(float), gi.max() + 1), jac=True, method="L-BFGS-B")
    return r.x


def evaluate(D, cols, beta):
    gi = pd.factorize(D.g)[0]; ng = gi.max() + 1
    u = D[cols].values @ beta if cols else np.zeros(len(D))
    e = np.exp(u - u.max()); den = np.bincount(gi, weights=e, minlength=ng); p = e / den[gi]
    y = D.y.values
    ll = float((y * np.log(p + 1e-12)).sum() / y.sum())
    S = D.assign(s=u + 1e-9 * np.random.default_rng(0).random(len(D)))
    r = S.groupby("g").s.rank(ascending=False, method="first")
    h1 = S[r <= 1].groupby("g").y.max(); h3 = S[r <= 3].groupby("g").y.max()
    return {"ll_per_choice": round(ll, 4), "hit1": round(float(h1.mean()), 3), "hit3": round(float(h3.mean()), 3),
            "by": {f"{k}={v}": {"hit1": round(float(h1[S.groupby("g")[k].first() == v].mean()), 3), "n": int((S.groupby("g")[k].first() == v).sum())}
                   for k in ("heavy", "tied") for v in (0.0, 1.0)}}


def main():
    D = build(); days = sorted(D.day.unique()); res = {"days": days, "choices": int(D.y.sum()), "person_days": int(D.g.nunique()),
                                                         "note": "exposure = final rank bucket (outcome-based): a preference decomposition, not a forecast"}
    specs = {"random": [], "exposure": EXPO, "taste": TASTE, "exposure+taste": EXPO + TASTE}
    split = days[len(days) // 2]
    tr, te = D[D.day < split], D[D.day >= split]
    res["forward"] = {"train_days": [days[0], days[len(days) // 2 - 1]], "test_days": [split, days[-1]]}
    for nm, cols in specs.items():
        b = fit(tr, cols) if cols else np.array([])
        res["forward"][nm] = evaluate(te, cols, b)
        if cols:
            res["forward"][nm]["coef"] = {c: round(float(v), 3) for c, v in zip(cols, b)}
    # leave-one-day-out, pooled held-out
    lodo = {nm: [] for nm in specs}
    for d in days:
        tr, te = D[D.day != d], D[D.day == d]
        for nm, cols in specs.items():
            b = fit(tr, cols) if cols else np.array([])
            e = evaluate(te, cols, b); e["day"] = d; lodo[nm].append(e)
    res["lodo_mean"] = {nm: {k: round(float(np.mean([x[k] for x in v])), 4) for k in ("ll_per_choice", "hit1", "hit3")} for nm, v in lodo.items()}
    json.dump(res, open(os.path.join(HERE, "results", "exposure_taste.json"), "w"), indent=1)
    print(json.dumps({k: res[k] for k in ("choices", "person_days", "lodo_mean")}, indent=1))
    print(json.dumps({nm: {k: v for k, v in res["forward"][nm].items() if k != "coef"} for nm in specs}, indent=1))
    print(json.dumps(res["forward"]["exposure+taste"]["coef"]))


if __name__ == "__main__":
    main()
