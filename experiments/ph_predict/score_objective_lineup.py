"""Score objective_lineup.py's out-of-fold predictions: daily top 3/5/10 per variant vs reg, paired day bootstrap; plus the
line-up second stage (ridge month-forward on the OOF reg score + line-up features). Days with all top-k ranked are used,
as honest.py per_day does.
usage: python score_objective_lineup.py <objective_lineup_preds.parquet> -> results/objective_lineup.json + .md"""
import json, os, sys
import numpy as np, pandas as pd
from scipy.stats import rankdata
HERE = os.path.dirname(os.path.abspath(__file__))


def per_day(A, col, k):
    return pd.Series({d: len(set(g.nlargest(k, col).id) & set(g[g.dailyRank <= k].id)) / k for d, g in A.groupby("day") if (g.dailyRank <= k).sum() == k})


def boot(d, rng):
    d = d.dropna().values; b = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(4000)]
    return [round(100 * float(d.mean()), 1), round(100 * float(np.percentile(b, 2.5)), 1), round(100 * float(np.percentile(b, 97.5)), 1)]


def stage2(A):
    from sklearn.linear_model import Ridge
    A = A.copy()
    g = A.groupby("day").reg
    A["s_gap"] = A.reg - g.transform("max")
    A["s_top5"] = g.transform(lambda s: s.nlargest(5).sum())
    F = ["reg", "s_gap", "s_top5", "lu_n_topic", "lu_sim_max", "lu_sim_mean"]
    X = A[F].fillna(A[F].median())
    A["stage2"] = np.nan
    mons = sorted(A.mon.unique())
    for m in mons[1:]:
        tr, te = A.mon < m, A.mon == m
        mu, sd = X[tr].mean(), X[tr].std() + 1e-9
        A.loc[te, "stage2"] = Ridge(alpha=1.0).fit((X[tr] - mu) / sd, A.logv[tr]).predict((X[te] - mu) / sd)
    return A


def main(path):
    rng = np.random.default_rng(0)
    A = pd.read_parquet(path); A = A[A.dailyRank.notna()]
    for c in ("reg", "lr_ndcg", "ridge"):
        A[f"r_{c}"] = A.groupby("day")[c].rank(pct=True)
    A["avg3"] = A[["r_reg", "r_lr_ndcg", "r_ridge"]].mean(axis=1)
    A["avg2"] = A[["r_reg", "r_lr_ndcg"]].mean(axis=1)   # without the (weak) ridge
    A = stage2(A)
    V = ["reg", "lr_ndcg", "lr_top3", "clf3", "clf10", "ridge", "avg3", "avg2", "reg_lu", "stage2"]
    res = {"days": int(A.day.nunique()), "launches": int(len(A)), "table": {}}
    md = ["# 00:05 launch model: objective / ensemble and same-day line-up features (honest, month-forward)", "",
          f"{A.day.nunique()} days, {len(A):,} launches; 5 seeds; paired day-bootstrap 95% CI vs reg.", "",
          "| variant | top 3 | top 5 | top 10 | minus reg: top 3 | top 5 | top 10 |", "|---|---|---|---|---|---|---|"]
    S2 = A.dropna(subset=["stage2"])
    for v in V:
        U = S2 if v == "stage2" else A
        base = {k: per_day(U, "reg", k) for k in (3, 5, 10)}
        cur = {k: per_day(U, v, k) for k in (3, 5, 10)}
        r = {f"top{k}": round(100 * float(cur[k].mean()), 1) for k in (3, 5, 10)}
        r.update({f"d{k}": boot(cur[k] - base[k], rng) for k in (3, 5, 10)})
        if v == "stage2":
            r["note"] = f"months after the first ({U.day.nunique()} days); reg on the same days = " + " / ".join(f"{100 * base[k].mean():.1f}" for k in (3, 5, 10))
        res["table"][v] = r
        md.append(f"| {v} | {r['top3']} | {r['top5']} | {r['top10']} | " + " | ".join(f"{r[f'd{k}'][0]:+.1f} [{r[f'd{k}'][1]:+.1f}, {r[f'd{k}'][2]:+.1f}]" for k in (3, 5, 10)) + " |")
    json.dump(res, open(os.path.join(HERE, "results", "objective_lineup.json"), "w"), indent=1)
    open(os.path.join(HERE, "results", "objective_lineup.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md)); print(res["table"]["stage2"].get("note"))


if __name__ == "__main__":
    main(sys.argv[1])
