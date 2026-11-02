"""Does E1 v2 add anything beyond day-level calibration? Same frozen setup as vote_model2_confirm.py (May–Oct, rolling
monthly, 5 seeds averaged, the same launches), paired by day / week (10,000 resamples):
  dayonly    control: launch-model offset + day terms only (rescales whole days, cannot reorder within a day)
  e1v2       offlive|pna, the packaged shadow model: offset + pna_ pool + live audiences + day terms
  e1v2 lr.05 / e1v2 leaves31: the same inputs with other LightGBM settings (is the daily result a settings effect?)
Reported: each against the launch model alone and against dayonly, on daily and weekly top 3/5/10 and log-likelihood;
months better on daily top 3 vs dayonly.
usage: SIMLAB_DATA=data_v2 python -m simlab.e1v2_vs_day -> reports/e1v2_vs_day.json"""
import json, os
import numpy as np, pandas as pd
from . import vote_model2 as V

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE_AUD = [c for c in V.AUD if c != "ph_maker_sum_followers"]
BASE = dict(n_estimators=300, learning_rate=0.02, num_leaves=15, min_child_samples=30, subsample=0.8, subsample_freq=1, colsample_bytree=0.7)
VARIANTS = {"dayonly": (V.DAY, BASE), "e1v2": (["pna_ev"] + LIVE_AUD + V.DAY, BASE),
            "e1v2 lr.05": (["pna_ev"] + LIVE_AUD + V.DAY, {**BASE, "learning_rate": 0.05}),
            "e1v2 leaves31": (["pna_ev"] + LIVE_AUD + V.DAY, {**BASE, "num_leaves": 31, "min_child_samples": 20})}


def fit_seed(tr, te, feats, params, seed):
    import lightgbm as lgb
    mono = [1 if f in ["pna_ev"] + LIVE_AUD else 0 for f in feats]
    c = np.log(tr.votes.sum() / np.expm1(tr["all"]).sum())
    m = lgb.LGBMRegressor(objective="poisson", random_state=seed, verbose=-1, n_jobs=8, monotone_constraints=mono, **params)
    m.fit(tr[feats], tr.votes, init_score=np.log(np.expm1(tr["all"]).clip(lower=0.5)) + c)
    return np.exp(m.predict(te[feats], raw_score=True) + np.log(np.expm1(te["all"]).clip(lower=0.5)) + c)


def main():
    A, _ = V.load(["pna"])
    A["week"] = pd.to_datetime(A.day).dt.strftime("%G-W%V")
    D = V.day_terms(A, "pna")
    months = sorted(D.mon.unique()); parts = []
    for m in months[1:]:
        tr, te = D[D.mon < m], D[D.mon == m].copy()
        c = tr.votes.sum() / np.expm1(tr["all"]).sum(); te["mu_lm"] = np.expm1(te["all"]).clip(lower=0.5) * c
        for name, (feats, params) in VARIANTS.items():
            te[f"mu_{name}"] = np.mean([fit_seed(tr, te, feats, params, s) for s in range(5)], 0)
        parts.append(te); print("month", m, flush=True)
    T = pd.concat(parts); rng = np.random.default_rng(0)
    res = {"launches": len(T), "days": int(T.day.nunique()), "weeks": int(T.week.nunique()), "months_tested": sorted(T.mon.unique()),
           "launch model alone": V.boards(T, "mu_lm", rng), "variants": {}}
    for name in VARIANTS:
        r = {"vs_launch_model": V.boards(T, f"mu_{name}", rng, base="mu_lm")}
        if name != "dayonly":
            r["vs_dayonly"] = {k.replace("_vs_lm", ""): v for k, v in V.boards(T, f"mu_{name}", rng, base="mu_dayonly").items() if k.endswith("_vs_lm")}
            mon = {m: (V.boards(g, f"mu_{name}", rng)["daily_top3"], V.boards(g, "mu_dayonly", rng)["daily_top3"]) for m, g in T.groupby("mon")}
            r["daily_top3_by_month_vs_dayonly"] = mon
        res["variants"][name] = r
    json.dump(res, open(os.path.join(HERE, "reports", "e1v2_vs_day.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
