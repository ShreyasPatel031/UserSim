"""Simulate the launch day: early supporters vote first, everyone after sees the page sorted by votes.

Inputs: data/vote_sim_scores_<TEST0>.npz from vote_sim2.py (each sample person's score for each launch, trained on
earlier months), plus the current launch model's percentile (prior: who posts it, product, site, competitors).
Per day:
  start   V_i = a * exp(g * prior_i)                       votes from outside our sample (the team's own reach)
  people  in order of how tied they are to the launch teams (follows / past backing first), in B batches;
          each person spreads act*per votes over launches with weight exp(s_ui / tau) * (1 + V_i) ** beta
          (beta > 0: what's already winning draws more votes — the page is sorted by votes)
Parameters (a, g, tau, beta, which person score) are chosen on Sep days, then scored once on Oct days.
Output: results/daysim.csv"""
import itertools, json, multiprocessing as mp, os, sys
import numpy as np, pandas as pd
from vote_sim import load, D, R

TEST0 = os.environ.get("TEST0", "2026-09-01")
TUNE_END = "2026-09-30"
B = 8


def recall(T, col, k):
    return np.mean([len(set(g.nsmallest(k, "rank").id) & set(g.nlargest(k, col).id)) / k
                    for _, g in T.groupby("day") if len(g) >= k])


def simulate(Z, day_rows, prior, a, gam, tau, beta, sc):
    """Returns expected final votes per launch for one day."""
    rows = day_rows
    la = Z["launch"][rows]; ul, li = np.unique(la, return_inverse=True)
    V = a * np.exp(gam * np.nan_to_num(prior[ul], nan=0.5))
    per, pe, s = Z["person"][rows], (Z["act"][rows] * Z["per"][rows]), Z[sc][rows] / tau
    tie = Z["f_hunter"][rows] + Z["f_team"][rows] + Z["hunter"][rows] + Z["recip"][rows]
    up, pi = np.unique(per, return_inverse=True)
    ptie = np.zeros(len(up)); np.maximum.at(ptie, pi, tie)
    order = np.argsort(-ptie + np.random.default_rng(0).random(len(up)) * 1e-6)
    batch = np.empty(len(up), int); batch[order] = np.arange(len(up)) * B // max(len(up), 1)
    rb = batch[pi]
    for b in range(B):
        m = rb == b
        if not m.any():
            continue
        w = s[m] + beta * np.log1p(V[li[m]])
        g = pi[m]
        w = np.exp(w - np.max(w))  # per-person softmax via group sums
        tot = np.bincount(g, w, len(up))
        V += np.bincount(li[m], pe[m] * w / tot[g], len(ul))
    return pd.Series(V, index=ul)


G = {}


def run_one(params):
    a, gam, tau, beta, sc = params
    Z, prior, by_day, T = G["Z"], G["prior"], G["by_day"], G["T"].copy()
    sim = pd.concat([simulate(Z, r, prior, a, gam, tau, beta, sc) for _, r in by_day.items()])
    T["_c"] = T.index.map(sim).fillna(-1) + np.random.default_rng(1).random(len(T)) * 1e-9
    tune, test = T[T.day <= TUNE_END], T[T.day > TUNE_END]
    return {"a": a, "g": gam, "tau": tau, "beta": beta, "score": sc,
            **{f"tune@{k}": recall(tune, "_c", k) for k in (3, 5, 10)},
            **{f"oct@{k}": recall(test, "_c", k) for k in (3, 5, 10)}}


def main():
    Z = dict(np.load(f"{D}/vote_sim_scores_{TEST0}.npz"))
    days = Z.pop("days")
    L = load()
    prior = L.prior.values
    by_day = pd.Series(np.arange(len(Z["dn"]))).groupby(Z["dn"]).indices
    T = L[L.day >= TEST0].copy()
    grid = list(itertools.product([0, 1, 5, 20], [0, 3, 6], [0.5, 1, 2], [0, 0.3, 0.6, 1.0], ["s0", "s1"]))
    G.update(Z=Z, prior=prior, by_day=by_day, T=T)
    grid = [x for x in grid if not (x[0] == 0 and x[1] > 0)]
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        res = pool.map(run_one, grid, chunksize=4)
    res = pd.DataFrame(res); res["tune"] = res[["tune@3", "tune@5", "tune@10"]].mean(1)
    res = res.sort_values("tune", ascending=False)
    res.to_csv(f"{R}/daysim.csv", index=False)
    Tt = T[T.day > TUNE_END]
    base = {f"oct@{k}": recall(Tt.assign(_c=Tt.pred.fillna(-1e3)), "_c", k) for k in (3, 5, 10)}
    print("current model on Oct:", {k: round(100 * v) for k, v in base.items()})
    print("best settings chosen on Sep, scored on Oct:")
    print((res.head(8).round(2)).to_string(index=False))
    for sc in ("s0", "s1"):
        print(sc, "best on Sep:", res[res.score == sc].head(1)[["a", "g", "tau", "beta", "oct@3", "oct@5", "oct@10"]].round(2).to_dict("records"))


if __name__ == "__main__":
    main()
