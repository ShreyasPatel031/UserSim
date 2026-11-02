"""Hypothesis (Nov 2): the CONCENTRATION of simulated pool support carries within-day signal the summed total does not.
Over the day-calibrated control (launch-model offset + day terms; shadow_daycal), add the person model's launch-level
aggregates beyond the total: picks from people already tied to the team (_ev_ties), the 100 most likely people (_fans),
people ranking the launch first / in their top 3 that day (_top1, _top3), the best single person (_pmax), and the
choice-style share (_share), each also as its standing within the day. Pool sources: pna_ (page-free, deployable) and
psa_ (page-aware, sensitivity). Same frozen setup as e1v2_vs_day.py (May–Oct, rolling monthly, 5 seeds averaged).
Decision rule fixed before the run: the hypothesis holds if daily top 3 vs the control has a 95% interval above 0.
usage: SIMLAB_DATA=data_v2 python -m simlab.pool_conc -> reports/pool_conc.json"""
import json, os
import numpy as np, pandas as pd
from . import vote_model2 as V

HERE = os.path.dirname(os.path.abspath(__file__))
AGG = ["ev", "ev_ties", "fans", "top1", "top3", "pmax", "share"]
PARAMS = dict(n_estimators=300, learning_rate=0.02, num_leaves=15, min_child_samples=30, subsample=0.8, subsample_freq=1, colsample_bytree=0.7)


def fit_seed(tr, te, feats, mono, seed):
    import lightgbm as lgb
    c = np.log(tr.votes.sum() / np.expm1(tr["all"]).sum())
    m = lgb.LGBMRegressor(objective="poisson", random_state=seed, verbose=-1, n_jobs=8, monotone_constraints=[1 if f in mono else 0 for f in feats], **PARAMS)
    m.fit(tr[feats], tr.votes, init_score=np.log(np.expm1(tr["all"]).clip(lower=0.5)) + c)
    return np.exp(m.predict(te[feats], raw_score=True) + np.log(np.expm1(te["all"]).clip(lower=0.5)) + c)


def main():
    srcs = ["pna", "psa"]
    A, _ = V.load(srcs)
    for s in srcs:   # every aggregate of each source, plus its standing within the day
        J = pd.DataFrame.from_dict(json.load(open(os.path.join(V.PH, "data", f"{s}_features.json"))), orient="index")
        cols = [f"{s}_{a}" for a in AGG if f"{s}_{a}" in J and f"{s}_{a}" not in A]
        A = A.merge(J[cols], left_on="id", right_index=True, how="left")
        for a in AGG:
            A[f"{s}_{a}_dayr"] = A.groupby("day")[f"{s}_{a}"].rank(pct=True)
    A["week"] = pd.to_datetime(A.day).dt.strftime("%G-W%V")
    D = V.day_terms(A, "pna")   # the control's day terms are the same in every variant
    variants = {"control (day-calibrated)": (V.DAY, set())}
    for s in srcs:
        conc = [f"{s}_{a}" for a in AGG] + [f"{s}_{a}_dayr" for a in AGG]
        variants[f"control + {s} total"] = (V.DAY + [f"{s}_ev", f"{s}_ev_dayr"], {f"{s}_ev"})
        variants[f"control + {s} concentration"] = (V.DAY + conc, {f"{s}_{a}" for a in AGG if a != "share"})
    months = sorted(D.mon.unique()); parts = []
    for m in months[1:]:
        tr, te = D[D.mon < m], D[D.mon == m].copy()
        c = tr.votes.sum() / np.expm1(tr["all"]).sum(); te["mu_lm"] = np.expm1(te["all"]).clip(lower=0.5) * c
        for name, (feats, mono) in variants.items():
            te[f"mu_{name}"] = np.mean([fit_seed(tr, te, feats, mono, s) for s in range(5)], 0)
        parts.append(te); print("month", m, flush=True)
    T = pd.concat(parts); rng = np.random.default_rng(0); ctrl = "mu_control (day-calibrated)"
    res = {"launches": len(T), "days": int(T.day.nunique()), "weeks": int(T.week.nunique()), "months_tested": sorted(T.mon.unique()),
           "decision_rule": "daily top 3 vs control, 95% interval above 0", "launch model alone": V.boards(T, "mu_lm", rng), "variants": {}}
    for name in variants:
        r = {"scores": V.boards(T, f"mu_{name}", rng)}
        if name != "control (day-calibrated)":
            r["vs_control"] = {k.replace("_vs_lm", ""): v for k, v in V.boards(T, f"mu_{name}", rng, base=ctrl).items() if k.endswith("_vs_lm")}
            mon = {m: (V.boards(g, f"mu_{name}", rng)["daily_top3"], V.boards(g, ctrl, rng)["daily_top3"]) for m, g in T.groupby("mon")}
            r["daily_top3_months_better_tied_worse"] = [sum(a > b for a, b in mon.values()), sum(a == b for a, b in mon.values()), sum(a < b for a, b in mon.values())]
            r["holds"] = bool(r["vs_control"]["daily_top3"][1][0] > 0)
        res["variants"][name] = r
    json.dump(res, open(os.path.join(HERE, "reports", "pool_conc.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
