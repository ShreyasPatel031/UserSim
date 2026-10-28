"""Simulation-only Product Hunt benchmark: launch lists predicted from simulated people alone (no launch-level model).
Per day (Apr-Oct), using only information dated before the day:
  people     everyone active in the 30 days before the day; w = share of those days active (chance of visiting)
  choice     p(person upvotes launch | sees it), the month's person model from popscore.py (no popularity input)
  ties       the person backed this team before (dated); optionally also follows (undated, reported separately)
  the day    S time slots; in each, a w/S share of every person visits and sees launch j with visibility
             v0 + (1 - v0) * exp(-(rank_j - 1) / tau), rank_j = its rank by SIMULATED votes so far (herding);
             a tied person sees it with at least beta. Simulated votes add up over the slots.
Free settings (S, tau, v0, beta) are fitted on Apr-Jun days only and tested on Jul-Oct, against the launch model
(non-simulation baseline), the same people without herding (S = 1, flat visibility) and random.
usage: SIMLAB_DATA=data_v2 python -m simlab.simbench rows [workers]  (per-person scores, once)
       python -m simlab.simbench fit -> reports/simbench.json"""
import itertools, json, os, pickle, sys
import multiprocessing as mp
import numpy as np, pandas as pd
from . import choice, harness as H
from . import popscore as PS

HERE = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(PS.WORK, "rows")
FIT_MONTHS = ("2026-04", "2026-05", "2026-06")


def rows_day(d):
    path = f"{ROWS}/{d}.parquet"
    if os.path.exists(path):
        return d, -1
    art = pickle.load(open(f"{PS.WORK}/model_{d[:7]}.pkl", "rb"))
    D = choice.rows(day_from=d, day_to=d, all_people=True)
    if not len(D):
        return d, 0
    D = PS.featurize(D, art["cf"], art["prior_cut"])
    D["p"] = art["model"].predict_proba(D[PS.FEATS])[:, 1]
    D[["person", "id", "w", "p", "backed", "follow"]].astype({"w": "float32", "p": "float32", "backed": "float32", "follow": "float32"}).to_parquet(path)
    return d, len(D)


def build_rows(workers):
    os.makedirs(ROWS, exist_ok=True); PS.load(); H.baseline()
    days = sorted(d for d in PS.G["lineup"] if d[:7] in PS.MONTHS and d <= "2026-10-24")
    with mp.get_context("fork").Pool(workers) as pool:
        for k, r in enumerate(pool.imap_unordered(rows_day, days)):
            if k % 20 == 0:
                print("rows", k, "of", len(days), r, flush=True)


def load_days():
    out = {}
    for f in sorted(os.listdir(ROWS)):
        D = pd.read_parquet(f"{ROWS}/{f}")
        ppl = {u: k for k, u in enumerate(D.person.unique())}; ids = list(D.id.unique()); lix = {x: k for k, x in enumerate(ids)}
        r, c = D.person.map(ppl).values, D.id.map(lix).values
        P = np.zeros((len(ppl), len(ids)), np.float32); P[r, c] = D.p.values
        T = np.zeros_like(P); T[r, c] = (D.backed.values > 0)
        F = np.zeros_like(P); F[r, c] = (D.follow.values > 0)
        w = np.zeros(len(ppl), np.float32); w[r] = D.w.values
        out[f[:10]] = (ids, w, P, T, F)
    return out


def simulate(day, S, tau, v0, beta, use_follow=False):
    ids, w, P, T, F = day
    tie = np.maximum(T, F) if use_follow else T
    votes = np.zeros(len(ids))
    rng = np.random.default_rng(0)
    jitter = rng.random(len(ids)) * 1e-9                          # launch order at 00:01 is unknown: a random tie-break
    for s in range(S):
        rank = np.argsort(np.argsort(-(votes + jitter))) + 1
        vis = v0 + (1 - v0) * np.exp(-(rank - 1) / tau)
        V = np.maximum(vis[None, :], beta * tie)
        votes += (w / S) @ (V * P)
    return dict(zip(ids, votes))


def score(sim, B, months):
    T = B[B.mon.isin(months)].copy(); T["sim"] = T.id.map(sim)
    T = T.dropna(subset=["sim"])
    out = {}
    for g, rc in (("day", "dailyRank"), ("week", "weeklyRank"), ("mon", "monthlyRank")):
        for k in H.KS:
            out[f"{g}@{k}"] = round(100 * H.recall(T, "sim", group=g, col=rc, k=k), 1)
    return out, T


_FIT = {}   # set before the pool forks, so workers share it


def _obj(th):
    sim = {}
    for v in _FIT["days"].values():
        sim.update(simulate(v, *th))
    return np.mean([score(sim, _FIT["B"], FIT_MONTHS)[0][f"day@{k}"] for k in H.KS]), th


def fit(days):
    B = H.baseline().drop_duplicates("id")
    grid = list(itertools.product((1, 4, 8, 16), (2, 5, 10, 25), (0.05, 0.2, 0.5, 1.0), (0.0, 0.5, 1.0)))
    _FIT.update(days={d: v for d, v in days.items() if d[:7] in FIT_MONTHS}, B=B)
    with mp.get_context("fork").Pool(os.cpu_count()) as pool:
        res = sorted(pool.map(_obj, grid), key=lambda r: -r[0])
    best = res[0][1]
    test = sorted({d[:7] for d in days} - set(FIT_MONTHS))
    variants = {"simulation: herding + ties (fitted)": dict(th=best), "simulation: no herding (S=1, flat)": dict(th=(1, 1e9, 1.0, 0.0)),
                "simulation: herding + ties incl. undated follows": dict(th=best, use_follow=True)}
    R = {"fitted_on": list(FIT_MONTHS), "tested_on": test, "best_settings": dict(zip(("S", "tau", "v0", "beta"), best)),
         "top_fits": [(round(r[0], 1), r[1]) for r in res[:5]]}
    for name, v in variants.items():
        sim = {}
        for dv in days.values():
            sim.update(simulate(dv, *v["th"], use_follow=v.get("use_follow", False)))
        R[name], T = score(sim, B, test)
    T["rnd"] = np.random.default_rng(0).random(len(T))
    for name, col in (("non-simulation launch model", "base"), ("random", "rnd")):
        R[name] = {f"{g}@{k}": round(100 * H.recall(T, col, group=g, col=rc, k=k), 1)
                   for g, rc in (("day", "dailyRank"), ("week", "weeklyRank"), ("mon", "monthlyRank")) for k in H.KS}
    json.dump(R, open(f"{HERE}/reports/simbench.json", "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in R.items() if k != "top_fits"}, indent=1, default=str))


def export(days):
    """Per-launch simulated votes with the fitted settings -> ph_predict/data/sim_features.json (a launch-model input)."""
    best = json.load(open(f"{HERE}/reports/simbench.json"))["best_settings"]
    th = (int(best["S"]), float(best["tau"]), float(best["v0"]), float(best["beta"]))
    out = {}
    for d, dv in days.items():
        sim, flat = simulate(dv, *th), simulate(dv, 1, 1e9, 1.0, 0.0)
        tot = sum(sim.values()) or 1.0
        r = {x: k + 1 for k, x in enumerate(sorted(sim, key=lambda x: -sim[x]))}
        for x in sim:
            out[str(x)] = {"sim_votes": float(sim[x]), "sim_votes_flat": float(flat[x]), "sim_share": float(sim[x] / tot),
                           "sim_rank": float(r[x])}
    json.dump(out, open(os.path.join(PS.store.RAW, "sim_features.json"), "w"))
    print("exported", len(out))


if __name__ == "__main__":
    if sys.argv[1] == "export":
        export(load_days())
    elif sys.argv[1] == "rows":
        build_rows(int(sys.argv[2]) if len(sys.argv) > 2 else os.cpu_count())
    else:
        fit(load_days())
