"""E0: where does the simulation's error live, in each person or in a shock shared by a launch's whole audience?
Inputs: popscore per-day files (S = psn_ev, the simulation's expected pool picks per launch; out of sample) and the
real pool votes R (people with an upvote or comment on the launch on its day).
1. Overdispersion. If people's errors were independent, R would be about Poisson(S) around the simulation, so
   Var(log((R+1)/(S+1))) would be about mean(1/(S+1)). The excess over that is the shared, launch-level shock.
   Reported within day (the day's mean log ratio removed).
2. Early-sample oracle. A random 10% of each launch's real pool voters is revealed (a stand-in for early votes); the
   rest (90%) is the target. Predictors of the held-out 90%, then of the final daily rank:
     sim         0.9 S                                   (no launch-day data)
     sample      9 R10                                   (launch-day data only)
     sim x shock 0.9 S (R10 + a) / (0.1 S + a)           (the simulation corrected by the launch's observed shock;
                                                          a fitted on Apr-Jun, applied to Jul-Oct)
   Within-day Spearman with the held-out pool votes; daily top 3 / 5 / 10 against final daily ranks; paired, day-
   clustered intervals. 20 random splits averaged.
usage: SIMLAB_DATA=data_v2 python -m simlab.e0_shock popscore_tie -> reports/e0_shock.json"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from . import store

HERE = os.path.dirname(os.path.abspath(__file__))


def main(src):
    P, I, E = store.load()
    day = dict(zip(I.id.astype(str), I.day)); rank = dict(zip(I.id.astype(str), I.out_dailyRank))
    E = E.assign(item=E.item.astype(str))
    voters = E[E.item.map(day) == E.date].groupby("item").person.apply(lambda s: np.array(sorted(set(s)))).to_dict()
    S = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(HERE, "cache", src, "day_*.parquet")))])
    S["id"] = S.id.astype(str); S["R"] = S.id.map(lambda x: len(voters.get(x, ()))); S["rank"] = S.id.map(rank)
    S["sim"] = S.psn_ev; S["mon"] = S.day.str[:7]
    res = {"source": src, "launches": len(S), "days": S.day.nunique()}
    # 1. overdispersion, within day
    S["lr"] = np.log((S.R + 1) / (S.sim + 1)); S["lr_w"] = S.lr - S.groupby("day").lr.transform("mean")
    poisson = float((1 / (S.sim + 1)).mean()); obs = float(S.lr_w.var())
    res["overdispersion"] = {"var_log_ratio_within_day": round(obs, 3), "expected_if_independent": round(poisson, 3),
                             "shared_shock_share": round(max(0.0, obs - poisson) / obs, 3),
                             "spearman_sim_vs_R_within_day": round(float(np.nanmean([spearmanr(g.sim, g.R).correlation for _, g in S.groupby("day") if len(g) >= 5])), 3)}
    # 2. early-sample oracle
    rng = np.random.default_rng(0)
    out = {k: {"spearman": {}, "top3": {}, "top5": {}, "top10": {}} for k in ("sim", "sample", "sim x shock")}

    def split(T, seed):
        r = np.random.default_rng(seed); R10, R90 = [], []
        for x in T.id:
            v = voters.get(x, np.array([])); m = r.random(len(v)) < 0.1
            R10.append(int(m.sum())); R90.append(int((~m).sum()))
        return np.array(R10), np.array(R90)
    fit, test = S[S.mon < "2026-07"].copy(), S[S.mon >= "2026-07"].copy()
    R10f, R90f = split(fit, 99)
    best_a, best = None, -9
    for a in (0.5, 1, 2, 5, 10, 20, 50):   # shrinkage fitted on Apr-Jun only
        pred = 0.9 * fit.sim.values * (R10f + a) / (0.1 * fit.sim.values + a)
        f2 = fit.assign(p=pred, t=R90f)
        sc = np.nanmean([spearmanr(g.p, g.t).correlation for _, g in f2.groupby("day") if len(g) >= 5])
        if sc > best:
            best, best_a = sc, a
    res["shrinkage_a"] = best_a
    acc = {k: {m: [] for m in ("spearman", "top3", "top5", "top10")} for k in out}
    for seed in range(20):
        R10, R90 = split(test, seed)
        T = test.assign(R10=R10, R90=R90)
        T["p_sim"] = 0.9 * T.sim; T["p_sample"] = 9 * T.R10 + 1e-6 * T.sim   # sim only breaks ties
        T["p_sim x shock"] = 0.9 * T.sim * (T.R10 + best_a) / (0.1 * T.sim + best_a)
        for k in out:
            col = "p_" + k; per = {}
            for d, g in T.groupby("day"):
                row = {"spearman": spearmanr(g[col], g.R90).correlation if len(g) >= 5 else np.nan}
                for kk in (3, 5, 10):
                    row[f"top{kk}"] = len(set(g.nlargest(kk, col).id) & set(g[g["rank"] <= kk].id)) / kk if (g["rank"] <= kk).sum() == kk else np.nan
                per[d] = row
            for m in acc[k]:
                acc[k][m].append(pd.Series({d: r[m] for d, r in per.items()}))
    days = sorted(test.day.unique()); res["oracle_jul_oct"] = {}
    mean_by_day = {k: {m: pd.concat(v, axis=1).mean(axis=1) for m, v in acc[k].items()} for k in acc}
    for k in acc:
        res["oracle_jul_oct"][k] = {m: round(float(100 * s.mean() if m != "spearman" else s.mean()), 3 if m == "spearman" else 1) for m, s in mean_by_day[k].items()}
    for a, b in (("sim", "sim x shock"), ("sample", "sim x shock"), ("sim", "sample")):
        line = {}
        for m in ("spearman", "top3", "top5", "top10"):
            d = (mean_by_day[b][m] - mean_by_day[a][m]).dropna().values
            bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(5000)]
            scale = 1 if m == "spearman" else 100
            line[m] = [round(scale * d.mean(), 3 if m == "spearman" else 1), [round(scale * x, 3 if m == "spearman" else 1) for x in np.percentile(bs, [2.5, 97.5])]]
        res["oracle_jul_oct"][f"{b} - {a}"] = line
    json.dump(res, open(os.path.join(HERE, "reports", "e0_shock.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
