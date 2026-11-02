"""E1 v2 follow-up 1: confirm "off" frozen as is (simlab/vote_model2.py), and test the deployable form.
Variants (rolling monthly, train on every earlier month, test the next; the same launches for all):
  off|psa      the reported variant: launch-model offset + pool (psa_) + audiences + day term
  off|pna      the same with the page-free pool pna_ (what the pipeline has at 00:05 PT)
  shadow|pna   launch-model offset + pool (pna_) + day term, no audiences: every input is in the 00:05 contract
               (forecast_<day>.parquet, sim_live/pnx_<day>.json)
Each is fitted with 5 LightGBM seeds separately (spread) and as their mean. Scores against the launch model alone:
daily and weekly top 3/5/10 and log-likelihood, paired by day / week (10,000 resamples), and month by month (wins of 6).
Also reports how far the inputs reach (for a fresh out-of-sample tail).
usage: SIMLAB_DATA=data_v2 python -m simlab.vote_model2_confirm -> reports/vote_model2_confirm.json"""
import json, os
import numpy as np, pandas as pd
from . import vote_model2 as V

HERE = os.path.dirname(os.path.abspath(__file__))
SEEDS = range(5)


def fit_seed(tr, te, feats, mono, seed):
    import lightgbm as lgb
    kw = dict(objective="poisson", n_estimators=300, learning_rate=0.02, num_leaves=15, min_child_samples=30, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.7, verbose=-1, n_jobs=8, monotone_constraints=[1 if f in mono else 0 for f in feats])
    c = np.log(tr.votes.sum() / np.expm1(tr["all"]).sum())
    m = lgb.LGBMRegressor(random_state=seed, **kw).fit(tr[feats], tr.votes, init_score=np.log(np.expm1(tr["all"]).clip(lower=0.5)) + c)
    return np.exp(m.predict(te[feats], raw_score=True) + np.log(np.expm1(te["all"]).clip(lower=0.5)) + c)


def main():
    A, _ = V.load(["psa", "pna"])
    A["week"] = pd.to_datetime(A.day).dt.strftime("%G-W%V")
    D = {s: V.maker_terms(V.day_terms(A.copy(), s), s).sort_values("id").reset_index(drop=True) for s in ("psa", "pna")}
    variants = {"off|psa": ("psa", ["psa_ev"] + V.AUD + V.DAY), "off|pna": ("pna", ["pna_ev"] + V.AUD + V.DAY),
                "shadow|pna": ("pna", ["pna_ev"] + V.DAY)}
    months = sorted(A.mon.unique()); T = None
    for name, (src, feats) in variants.items():
        X = D[src]; mono = set([f"{src}_ev"] + V.AUD); parts = []
        for m in months[1:]:
            tr, te = X[X.mon < m], X[X.mon == m].copy()
            c = tr.votes.sum() / np.expm1(tr["all"]).sum(); te["mu_lm"] = np.expm1(te["all"]).clip(lower=0.5) * c
            P = [fit_seed(tr, te, feats, mono, s) for s in SEEDS]
            for s, p in zip(SEEDS, P):
                te[f"mu_{name}#s{s}"] = p
            te[f"mu_{name}"] = np.mean(P, 0)
            parts.append(te)
        Y = pd.concat(parts)
        keep = ["id"] + [c for c in Y if c.startswith(f"mu_{name}")]
        T = Y if T is None else T.merge(Y[keep], on="id")
        print("done", name, flush=True)
    rng = np.random.default_rng(0)
    res = {"launches": len(T), "days": int(T.day.nunique()), "weeks": int(T.week.nunique()), "months_tested": sorted(T.mon.unique()),
           "inputs_reach": {"launch model (ctrl_preds)": str(A.day.max()), "pool psa_/pna_": str(A.day.max())},
           "launch model alone": V.boards(T, "mu_lm", rng), "variants": {}}
    for name in variants:
        r = {"seed_mean": V.boards(T, f"mu_{name}", rng, base="mu_lm")}
        per_seed = [V.boards(T, f"mu_{name}#s{s}", rng) for s in SEEDS]
        r["per_seed"] = {k: [p[k] for p in per_seed] for k in ("daily_top3", "daily_top5", "daily_top10", "weekly_top3", "weekly_top5", "weekly_top10", "loglik")}
        r["seed_spread"] = {k: {"mean": round(float(np.mean(v)), 2), "sd": round(float(np.std(v)), 2), "min": min(v), "max": max(v)} for k, v in r["per_seed"].items()}
        mon = {}
        for m, g in T.groupby("mon"):
            b = V.boards(g, f"mu_{name}", rng); l = V.boards(g, "mu_lm", rng)
            mon[m] = {k: [b[f"daily_top{k}"], l[f"daily_top{k}"]] for k in (3, 5, 10)}
        r["by_month"] = mon
        r["months_better"] = {f"daily_top{k}": f"{sum(v[k][0] > v[k][1] for v in mon.values())} better, {sum(v[k][0] == v[k][1] for v in mon.values())} tied of {len(mon)}" for k in (3, 5, 10)}
        res["variants"][name] = r
    T[["id", "day", "week", "mon", "dailyRank", "out_weeklyRank", "votes", "mu_lm"] + [c for c in T if c.startswith("mu_") and c != "mu_lm"]].to_parquet(
        os.path.join(V.PH, "results", "vote_model2_confirm.parquet"))
    json.dump(res, open(os.path.join(HERE, "reports", "vote_model2_confirm.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "variants"}, indent=1))
    for name, r in res["variants"].items():
        print(name, json.dumps({"seed_mean": {k: v for k, v in r["seed_mean"].items()}, "seed_spread": r["seed_spread"], "months_better": r["months_better"]}))


if __name__ == "__main__":
    main()
