"""Score lineup_thin_arm3.py predictions: per day, hits vs the FULL day's true top k (removed launches in the true top k are misses),
averaged over the 20 thinned draws; full (unthinned) test as reference. Paired day bootstrap (10,000) on the >= 10-ranked day rule (183),
all 214, and the last 90 of the 183. usage: python3 lineup_thin_score.py <out dir> (reads preds.parquet, rows.json; needs dailyRank via
results/history_retrain_decomp_preds_arm2.parquet)."""
import json, sys
import numpy as np, pandas as pd
O = sys.argv[1]; R = pd.read_parquet(f"{O}/preds.parquet"); R["id"] = R.id.astype(str)
T = pd.read_parquet("results/history_retrain_decomp_preds_arm2.parquet")[["id", "day", "dailyRank"]]; T["id"] = T.id.astype(str)
T = T.dropna(subset=["dailyRank"]); truth = {d: g.sort_values("dailyRank").id.tolist() for d, g in T.groupby("day")}
nr = T.groupby("day").size(); D10 = sorted(nr[nr >= 10].index); KS = (3, 5, 10)
def day_hits(g, d):
    o = g.sort_values(["pred", "id"], ascending=[False, True]).id.tolist(); t = truth[d]
    return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in KS]
H = {}
for (mdl, dr), g in R.groupby(["model", "draw"]):
    for d, gg in g.groupby("day"):
        if d in truth: H.setdefault((mdl, "full" if dr < 0 else "thin", d), []).append(day_hits(gg, d))
S = {k: np.mean(v, 0) for k, v in H.items()}
models = sorted(R.model.unique()); rng = np.random.default_rng(0); L = []
def arr(mdl, cond, days): return np.array([S[(mdl, cond, d)] for d in days])
def cmp(a, b, cond, days):
    x = arr(a, cond, days) - arr(b, cond, days); bs = np.array([x[rng.integers(0, len(x), len(x))].mean(0) for _ in range(10000)])
    return " / ".join(f"{x[:, k].mean():+.1f} [{np.percentile(bs[:, k], 2.5):+.1f}, {np.percentile(bs[:, k], 97.5):+.1f}]" for k in range(3))
for cut, days in ((">=10 ranked (183)", D10), ("all 214", sorted(truth)), ("last 90 of 183", D10[-90:])):
    days = [d for d in days if all((m, "thin", d) in S for m in models)]
    L.append(f"\n### {cut}: {len(days)} days")
    for cond in ("thin", "full"):
        L.append(f"levels ({cond} test): " + "; ".join(f"{m} {arr(m, cond, days).mean(0).round(1).tolist()}" for m in models))
    for lab, a, b in (("(2)-(1) drop", "m2d", "m1"), ("(2)-(1) keep", "m2k", "m1"), ("(4)-(2) drop [primary]", "m4d", "m2d"),
                      ("(4)-(2) keep", "m4k", "m2k"), ("(4)-(1) drop", "m4d", "m1"), ("(4)-(1) keep", "m4k", "m1"), ("(3)-(1)", "m3", "m1")):
        L.append(f"{lab}, thinned test: {cmp(a, b, 'thin', days)}")
L.append("\nrows: " + open(f"{O}/rows.json").read().replace("\n", " "))
print("\n".join(L)); open(f"{O}/score.md", "w").write("\n".join(L) + "\n")
