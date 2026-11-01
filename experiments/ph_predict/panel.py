"""The pool as a polling panel, reweighted to the whole audience. The launch forecast is the reweighted sum of
simulated picks, with no launch-level model on top:
    votes_x  ~  sum over segments s of  beta_s * S_xs
where S_xs is the simulation's expected picks for launch x from pool people in segment s (popscore SEG=1: activity x
tie type x maker x Product Hunt followers, 54 segments), and beta_s >= 0 is how many Product Hunt voters one simulated
pick in that segment stands for. beta is fitted on earlier months only (non-negative least squares, rows weighted
1/sqrt(votes + 10) as a Poisson-like variance), then applied to the next month. Variants:
  panel            the reweighted sum (simulation only)
  pool sum         beta_s = 1: the raw simulated pool picks (simulation only)
  launch model     ctrl.py launch model, all inputs
  blend            mean of the within-day percentile ranks of panel and launch model
Metrics: daily top 3 / 5 / 10 (days whose real top k is complete), winner of 3 competitors (comp_test.py's groups:
same day / week / month, sharing a specific topic), paired bootstrap over days for panel vs pool sum and blend vs launch model.
usage: python panel.py <popscore cache dir, e.g. ../simlab/cache/popscore_tie_seg> -> results/panel.json"""
import glob, json, os, sys
from collections import Counter
import numpy as np, pandas as pd
from scipy.optimize import nnls


def load(d):
    S = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f"{d}/day_*.parquet"))]); S["id"] = S.id.astype(str)
    seg = sorted([c for c in S if c.startswith("seg_")], key=lambda c: int(c[4:]))
    S[seg] = S[seg].fillna(0.0)
    return S, seg


def topk(T, col, k):
    return [len(set(g.nlargest(k, col).id) & set(g[g.dailyRank <= k].id)) / k for _, g in T.groupby("day") if (g.dailyRank <= k).sum() == k]


def per_day(T, col, k):
    return pd.Series({d: len(set(g.nlargest(k, col).id) & set(g[g.dailyRank <= k].id)) / k for d, g in T.groupby("day") if (g.dailyRank <= k).sum() == k})


def winner3(T, P):
    days = {}
    for f in glob.glob("data/days/*.json"):
        for p in json.load(open(f)):
            t = p.get("topics") or []
            days[str(p["id"])] = [e["node"]["name"] for e in t.get("edges", [])] if isinstance(t, dict) else [x["name"] if isinstance(x, dict) else x for x in t]
    T = T.copy(); T["topics"] = T.id.map(lambda i: days.get(i, []))
    freq = Counter(t for ts in T.topics for t in ts); generic = {t for t, _ in freq.most_common(6)}
    T["spec"] = T.topics.map(lambda ts: [t for t in ts if t not in generic])
    T["week"] = pd.to_datetime(T.day).dt.strftime("%G-W%V")
    rng = np.random.default_rng(0); res = {}
    for win in ("day", "week", "mon"):
        trip = {p: [] for p in P}
        for _, g in T.groupby(win):
            g = g.reset_index(drop=True); bytopic = {}
            for i, ts in enumerate(g.spec):
                for t in ts:
                    bytopic.setdefault(t, []).append(i)
            for i in range(len(g)):
                comp = sorted({j for t in g.spec[i] for j in bytopic[t] if j != i})
                if len(comp) < 2:
                    continue
                js = list(rng.choice(comp, 2, replace=False)); grp = g.loc[[i] + js]
                if grp.logv.nunique() < 3:
                    continue
                for p in P:
                    trip[p].append(grp[p].idxmax() == grp.logv.idxmax())
        res[win] = {"groups_of_3": len(trip[P[0]]), **{p: round(100 * float(np.mean(trip[p])), 1) for p in P}}
    return res


def boot(T, a, b, k, rng):
    A, B = per_day(T, a, k), per_day(T, b, k); d = (B - A).dropna().values
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(5000)]
    return [round(100 * float(d.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])], len(d)]


def main(src):
    S, seg = load(src)
    C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str)
    T = C[["id", "day", "dailyRank", "logv", "all"]].merge(S[["id"] + seg], on="id")
    T["votes"] = np.expm1(T.logv); T["mon"] = T.day.str[:7]
    out, betas = [], {}
    for m in sorted(T.mon.unique())[1:]:
        tr, te = T[T.mon < m], T[T.mon == m].copy()
        wt = 1 / np.sqrt(tr.votes.values + 10)
        beta, _ = nnls(tr[seg].values * wt[:, None], tr.votes.values * wt)
        te["panel"] = te[seg].values @ beta; te["pool sum"] = te[seg].sum(1)
        betas[m] = {s: round(float(b), 2) for s, b in zip(seg, beta) if b > 0}
        out.append(te)
    T = pd.concat(out).rename(columns={"all": "launch model"})
    for c in ("panel", "launch model"):
        T[c + "_r"] = T.groupby("day")[c].rank(pct=True)
    T["blend"] = (T["panel_r"] + T["launch model_r"]) / 2
    P = ["panel", "pool sum", "launch model", "blend"]; rng = np.random.default_rng(0)
    res = {"source": src, "months_tested": sorted(T.mon.unique()), "launches": len(T), "segments": len(seg),
           "segments_with_weight": {m: len(b) for m, b in betas.items()}}
    for months, lab in ((sorted(T.mon.unique()), "all months"), ([m for m in sorted(T.mon.unique()) if m >= "2026-07"], "Jul-Oct")):
        U = T[T.mon.isin(months)]
        res[lab] = {"daily top 3/5/10": {p: [round(100 * float(np.mean(topk(U, p, k))), 1) for k in (3, 5, 10)] for p in P},
                    "panel - pool sum": {f"top {k}": boot(U, "pool sum", "panel", k, rng) for k in (3, 5, 10)},
                    "blend - launch model": {f"top {k}": boot(U, "launch model", "blend", k, rng) for k in (3, 5, 10)},
                    "panel - launch model": {f"top {k}": boot(U, "launch model", "panel", k, rng) for k in (3, 5, 10)},
                    "winner of 3": winner3(U, P)}
    res["largest_weights_last_month"] = dict(sorted(betas[max(betas)].items(), key=lambda kv: -kv[1])[:8])
    json.dump(res, open("results/panel.json", "w"), indent=1); print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
