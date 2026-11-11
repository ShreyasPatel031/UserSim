"""Iteration 9: day-dynamic cascade simulation (orchestrator Nov 11; pre-registered with E5, PASS as a shadow).

Inputs per launch L on day d, all known at 00:05 PT, from it8's A x K x S rows (rows_tl_cp_choice/<d>.parquet, q = w*p)
joined to the base feature rows (rows_tl_cp_unc/X_<d>.parquet, `backed` = the person backed L's team before d):
  S_L = sum q over people with backed > 0   (team-tied seed cohort)
  G_L = sum q over everyone else            (broad taste)
Dynamics, 96 steps of 15 min from 00:00 PT:
  dv_L(t) = s * S_L * hs[block(t)] + g * G_L * hd[block(t)] * E(t, rank_L(t))
  blocks 00-02, 02-06, 06-12, 12-24 PT (hs[0] = hd[0] = 1); rank_L(t) = rank by simulated votes (ties: G_L)
  E = 1 for t < 4 h (PH hides counts; exposure = default order only, E5 condition 3), else e[bucket(rank)] with buckets
  1, 2-3, 4-5, 6-10, 11-20, 21+, e[0] = 1, monotone non-increasing. 13 parameters.
Fit: least squares of log1p(simulated) vs log1p(real) cumulative votes at every 15-min snapshot of the training days
(raw/ph_at_launch/<d>/live/posts_ts.jsonl votes_at_fetch). Two schemes (E5 condition 1):
  (i)  leave-one-day-out over the trajectory days;   (ii) forward-only: each test day fitted on earlier days only.
Scored: end-of-day simulated rank vs the real daily rank, daily top 3/5/10, against the LM (forecasts), it8 static EV
(S + G), S-only and G-only static orders, on the same days. Secondary, labelled "uses observed votes": the same sim
started at 1 h and 4 h from the real votes, vs the real rank at that hour; never part of the keep decision.
usage: SIMBT=<dir> CASCADE_DIR=<dir with traj.parquet> python cascade.py -> results/cascade.json"""
import json, os, sys
import numpy as np, pandas as pd
from scipy.optimize import minimize

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
WORK = os.environ["SIMBT"]; CD = os.environ["CASCADE_DIR"]
STEPS = np.arange(96) * 15.0
BLOCK = np.searchsorted([120, 360, 720], STEPS, side="right")   # 0: 00-02, 1: 02-06, 2: 06-12, 3: 12-24 PT
BUCKETS = np.array([1, 3, 5, 10, 20])                          # rank <= 1 | <= 3 | <= 5 | <= 10 | <= 20 | > 20
NPAR = 13


def unpack(th):
    s, g = np.exp(th[0]), np.exp(th[1])
    hs = np.r_[1.0, np.exp(th[2:5])]; hd = np.r_[1.0, np.exp(th[5:8])]
    e = np.r_[1.0, np.exp(-np.cumsum(np.log1p(np.exp(th[8:13]))))]   # monotone non-increasing, e[0] = 1
    return s, g, hs, hd, e


def simulate(th, S, G, start_t=0.0, v0=None):
    """Cumulative simulated votes at each step (len(STEPS) x n). With v0, the run starts at start_t from those votes."""
    s, g, hs, hd, e = unpack(th)
    n = len(S); v = np.zeros(n) if v0 is None else v0.astype(float).copy(); out = np.zeros((len(STEPS), n))
    for k, t in enumerate(STEPS):
        if t >= start_t:
            if t < 240:
                E = np.ones(n)
            else:
                order = np.lexsort((-G, -v)); rank = np.empty(n, int); rank[order] = np.arange(1, n + 1)
                E = e[np.searchsorted(BUCKETS, rank, side="left")]
            v = v + s * S * hs[BLOCK[k]] + g * G * hd[BLOCK[k]] * E
        out[k] = v
    return out


def load_days():
    from pipeline import warehouse as W
    T = pd.read_parquet(f"{CD}/traj.parquet")
    L = W.query("SELECT CAST(id AS VARCHAR) AS id, day::VARCHAR AS day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
    rk = dict(zip(L.id, L.daily_rank))
    Fc = W.query("SELECT CAST(launch_id AS VARCHAR) AS id, forecast_date AS day, predicted_rank FROM forecasts WHERE model = 'launch_model'", do_sync=False)
    lm = {(r.day, r.id): r.predicted_rank for r in Fc.itertuples()}
    days = {}
    for d, g in T.groupby("day"):
        if g.ts.nunique() < 40 or g.t_min.max() < 1000:   # needs a near-full day of 15-min snapshots
            continue
        rp, xp = f"{WORK}/rows_tl_cp_choice/{d}.parquet", f"{WORK}/rows_tl_cp_unc/X_{d}.parquet"
        if not (os.path.exists(rp) and os.path.exists(xp)):
            continue
        R = pd.read_parquet(rp, columns=["person", "id", "w", "p"]); X = pd.read_parquet(xp, columns=["person", "id", "backed"])
        R["id"] = R.id.astype(str); X["id"] = X.id.astype(str)
        R = R.merge(X, on=["person", "id"], how="left"); R["q"] = R.w * R.p
        S = R[R.backed > 0].groupby("id").q.sum(); Gs = R[~(R.backed > 0)].groupby("id").q.sum()
        ids = sorted(set(g.id))
        V = g.pivot_table(index="t_min", columns="id", values="votes", aggfunc="max").reindex(columns=ids).sort_index().ffill().fillna(0)
        days[d] = {"ids": ids, "S": np.array([S.get(i, 0.0) for i in ids]), "G": np.array([Gs.get(i, 0.0) for i in ids]),
                   "t": V.index.values.astype(float), "V": V.values, "rank": np.array([rk.get(i, np.nan) for i in ids], float),
                   "lm": np.array([lm.get((d, i), np.nan) for i in ids], float), "n_it8": int(R.id.nunique())}
    return days


def loss(th, days):
    tot = 0.0
    for D in days:
        sim = simulate(th, D["S"], D["G"])
        idx = np.clip(np.searchsorted(STEPS, D["t"], side="right") - 1, 0, len(STEPS) - 1)
        tot += float(((np.log1p(sim[idx]) - np.log1p(D["V"])) ** 2).mean())
    return tot / max(1, len(days))


def fit(days):
    best = None
    for s0 in (0, 1, 2):   # a few starts; Powell on 13 parameters
        th0 = np.r_[np.log(1 + s0), 0.0, np.zeros(6), np.zeros(5)]
        r = minimize(loss, th0, args=(days,), method="Powell", options={"maxiter": 4000, "xtol": 1e-3, "ftol": 1e-5})
        if best is None or r.fun < best.fun:
            best = r
    return best.x, float(best.fun)


def topk(score, rank, k, asc=False):
    ok = ~np.isnan(rank); top = set(np.where(ok & (rank <= k))[0])
    if len(top) < k or np.isnan(score[ok]).all():
        return np.nan
    s = np.where(np.isnan(score), -np.inf if not asc else np.inf, score)
    pick = np.argsort(s)[:k] if asc else np.argsort(-s)[:k]
    return len(set(pick) & top) / k * 100


def boot(x, rng, n=10000):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    if len(x) < 2:
        return [round(float(x.mean()), 1) if len(x) else None, None, int(len(x))]
    b = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)]
    return [round(float(x.mean()), 1), [round(float(v), 1) for v in np.percentile(b, [2.5, 97.5])], int(len(x))]


def main():
    days = load_days(); names = sorted(days)
    res = {"days": names, "n_params": NPAR, "launches_per_day": {d: len(days[d]["ids"]) for d in names}}
    fits = {"loo": {d: [days[x] for x in names if x != d] for d in names},
            "forward": {d: [days[x] for x in names if x < d] for d in names if any(x < d for x in names)}}
    rng = np.random.default_rng(0)
    for scheme, tr in fits.items():
        per, pars, cond = [], {}, []
        for d, train in tr.items():
            th, l = fit(train); pars[d] = {"loss": round(l, 4), "theta": [round(float(v), 3) for v in th]}
            D = days[d]; sim = simulate(th, D["S"], D["G"]); end = sim[-1]
            row = {"day": d}
            for k in (3, 5, 10):
                row[f"cascade_top{k}"] = topk(end, D["rank"], k)
                row[f"it8_top{k}"] = topk(D["S"] + D["G"], D["rank"], k)
                row[f"S_top{k}"] = topk(D["S"], D["rank"], k)
                row[f"G_top{k}"] = topk(D["G"], D["rank"], k)
                row[f"lm_top{k}"] = topk(D["lm"], D["rank"], k, asc=True) if np.isfinite(D["lm"]).sum() >= k else np.nan
            per.append(row)
            for h in (60, 240):   # conditional: uses observed votes up to h
                j = np.searchsorted(D["t"], h, side="right") - 1
                if j < 0:
                    continue
                v0 = D["V"][j]; simc = simulate(th, D["S"], D["G"], start_t=h, v0=v0)[-1]
                c = {"day": d, "h": h}
                for k in (3, 5, 10):
                    c[f"cond_top{k}"] = topk(simc, D["rank"], k); c[f"real_at_h_top{k}"] = topk(v0 + 1e-6 * D["G"], D["rank"], k)
                cond.append(c)
        P = pd.DataFrame(per); C = pd.DataFrame(cond); r = {"fits": pars, "per_day": per}
        for k in (3, 5, 10):
            line = {m: boot(P[f"{m}_top{k}"], rng) for m in ("cascade", "it8", "S", "G", "lm")}
            for ref in ("lm", "it8", "S", "G"):
                d_ = (P[f"cascade_top{k}"] - P[f"{ref}_top{k}"]).values
                line[f"cascade_minus_{ref}"] = boot(d_, rng)
            r[f"top{k}"] = line
        r["conditional_uses_observed_votes"] = {f"h{h}_top{k}": {"cascade": boot(C[C.h == h][f"cond_top{k}"], rng),
                                                                 "real_rank_at_h": boot(C[C.h == h][f"real_at_h_top{k}"], rng)}
                                                for h in (60, 240) for k in (3, 5, 10)} if len(C) else {}
        th = np.array([v["theta"] for v in pars.values()])
        r["theta_spread_sd"] = [round(float(x), 3) for x in th.std(0)] if len(th) > 1 else None
        res[scheme] = r
    # keep rule (E5): on forward days, cascade beats the LM at top 3 and top 5 with at least one CI-positive, no k negative
    F = res.get("forward", {})
    if F:
        dl = {k: F[f"top{k}"]["cascade_minus_lm"] for k in (3, 5, 10)}
        res["keep"] = {"deltas_vs_lm": dl, "KEEP": bool(all(dl[k][0] is not None and dl[k][0] > 0 for k in (3, 5))
                                                       and any(dl[k][1] and dl[k][1][0] > 0 for k in (3, 5))
                                                       and all(dl[k][0] is None or dl[k][0] >= 0 for k in (3, 5, 10)))}
    json.dump(res, open(os.path.join(HERE, "results", "cascade.json"), "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in res.items() if k not in ("loo", "forward")}, default=float))
    for sc in ("loo", "forward"):
        if sc in res:
            print(sc, json.dumps({k: res[sc][k] for k in ("top3", "top5", "top10", "theta_spread_sd")}, default=float))


if __name__ == "__main__":
    main()
