"""Weekly magnitude model (orchestrator, Nov 3): a pre-launch transform of the honest launch prior to total-vote scale,
for the weekly and monthly boards. Two parts:
  1. Position feedback, fitted on the clean hourly vote_snapshots (deduped as pipeline/snapshots.py: one row per launch
     and UTC hour, earliest kept; clean from Nov 2): votes gained in an hour ~ Poisson(exp(a_launch + f(rank at the hour's
     start) + g(hour of the launch day))). f is the exposure of a leaderboard position.
  2. Each day's line-up simulated hour by hour (mean field): quality q_i = mu_i^alpha with mu_i the honest prior's expected
     votes; every hour launches are ranked by votes so far and gain q_i * exp(f(rank)) * exp(g(hour)); the day's final
     shares come from 24 hours of that. The day's level is the day-calibrated control's total (daycal.py: offset = honest,
     day terms day_wd, day_n, day_lm_sum, trail_real7, trail_lm7 ending d-2; rolling monthly, 5 seeds). alpha is chosen per
     test month by Poisson log-likelihood on the earlier months.
  Score of a launch = control day total x simulated share. Within a day the order is the prior's (q is monotone in mu),
  so the daily board is unchanged; only the weekly / monthly boards can move.
Inputs at 00:05 PT only: honest prior per launch, line-up size, weekday, trailing real totals ending d-2, and A2 (dated
team comments; optional, A2=<parquet>, as a per-launch quality multiplier exp(beta * a2_act14_log), beta fitted like alpha).
GATE (registered before any run): weekly top 3 vs the day-calibrated control, paired by week (10,000 resamples),
95% interval above 0. Also reported: weekly top 5 / 10, monthly top 3 / 5 / 10 (point values per month).
DRY RUN (Nov 3): the feedback curve has 2 clean days; shape and leak checks only. The real fit needs 14 clean days.
usage: SIMLAB_DATA=data_v2 OFFSET=results/honest_preds.parquet:honest [A2=...] python -m simlab.day_strength <snapshot dir>
       (run from ph_predict/, like daycal.py) -> results/day_strength.json"""
import glob, json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from simlab import store

RANK = {"week": "out_weeklyRank", "mon": "out_monthlyRank", "day": "out_dailyRank"}
COLS = ["day_wd", "day_n", "day_lm_sum", "trail_real7", "trail_lm7"]
CLEAN_FROM = "2026-11-02"
ALPHAS = (0.15, 0.25, 0.35, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
GATE = "weekly top 3 vs the day-calibrated control, paired by week, 95% interval above 0"


def load_snapshots(src):
    rows = []
    for f in sorted(glob.glob(os.path.join(src, "*.jsonl"))):
        rows += [json.loads(l) for l in open(f) if l.strip()]
    S = pd.DataFrame(rows)
    P = [pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(src, "*.parquet")))]
    if P:
        S = pd.concat([S] + P, ignore_index=True)
    S = S.assign(launch_id=S.launch_id.astype(str), hour=S["at"].astype(str).str[:13])          # pipeline/snapshots.py dedupe
    return S.sort_values("at").drop_duplicates(["launch_id", "hour"], keep="first").reset_index(drop=True)


def feedback(S, max_rank=20):
    """exposure by rank f(r) and by hour of the day g(h), with a launch effect, on clean days."""
    from sklearn.linear_model import PoissonRegressor
    S = S[S.day >= CLEAN_FROM].sort_values(["launch_id", "at"])
    S = S.assign(next_votes=S.groupby("launch_id").votes.shift(-1), next_h=S.groupby("launch_id").hours_since_start.shift(-1))
    S = S[S.next_votes.notna() & ((S.next_h - S.hours_since_start).between(0.5, 1.5))]
    S = S.assign(dv=(S.next_votes - S.votes).clip(lower=0), r=S.rank_now.clip(upper=max_rank).astype(int),
                 h=(S.hours_since_start.astype(float).clip(0, 23.99) // 4).astype(int))     # 4-hour blocks (stable with few days)
    X = pd.concat([pd.get_dummies(S.launch_id, prefix="L"), pd.get_dummies(S.r, prefix="r").drop(columns="r_1", errors="ignore"),
                   pd.get_dummies(S.h, prefix="h").drop(columns="h_0", errors="ignore")], axis=1).astype(float)
    m = PoissonRegressor(alpha=1e-4, max_iter=3000).fit(X, S.dv)
    co = pd.Series(m.coef_, index=X.columns)
    f = np.array([0.0] + [co.get(f"r_{r}", np.nan) for r in range(2, max_rank + 1)])
    f = pd.Series(f).interpolate().ffill().to_numpy()
    f = np.minimum.accumulate(f)                                  # a lower position never gets more exposure
    gb = np.array([0.0] + [co.get(f"h_{h}", np.nan) for h in range(1, 6)])
    gb = pd.Series(gb).interpolate().ffill().bfill().to_numpy(); g = np.repeat(gb, 4)
    info = {"clean_days": sorted(S.day.unique()), "launch_hours": int(len(S)), "launches": int(S.launch_id.nunique()),
            "exp_f_rank_1_to_20": [round(float(x), 3) for x in np.exp(f)], "exp_g_hour_0_to_23": [round(float(x), 3) for x in np.exp(g)]}
    return f, g, info


def shares(mu, f, g, alpha, mult=None):
    """24 hourly steps, mean field; ties at the start broken by quality."""
    q = np.power(np.asarray(mu, float), alpha) * (1 if mult is None else np.asarray(mult, float))
    v = np.zeros(len(q)); ef, eg = np.exp(f), np.exp(g)
    for h in range(24):
        order = np.lexsort((-q, -v))                               # by votes, then quality
        rank = np.empty(len(q), int); rank[order] = np.arange(len(q))
        v += q * ef[np.minimum(rank, len(ef) - 1)] * eg[h]
    return v / v.sum()


def per_list(T, col, key, k):
    return pd.Series({g_: len(set(g.nlargest(k, col).id) & set(g[g[RANK[key]] <= k].id)) / k for g_, g in T.groupby(key) if (g[RANK[key]] <= k).sum() == k})


def boot(a, b, rng):
    ks = a.index.intersection(b.index); d = (b[ks] - a[ks]).values
    if len(d) < 2:
        return [round(100 * float(d.mean()), 1) if len(d) else None, None, int(len(d))]
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(10000)]
    return [round(100 * float(d.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])], int(len(d))]


def main(snap_dir):
    res = {"gate": GATE}
    S = load_snapshots(snap_dir)
    f, g, info = feedback(S); res["feedback"] = info
    param = os.environ.get("CURVE") == "param"
    if param:   # honest variant: no snapshots; f = log(b) at rank 1, 0 below; b and alpha chosen on the training months
        res["variant"] = "parametric rank-1 bonus fitted on training months (no snapshots, no look-ahead)"
    elif os.environ.get("FLAT"):          # control for the curve: no position feedback, shares = q / sum q
        f, g = np.zeros_like(f), np.zeros_like(g); res["variant"] = "flat feedback (power transform of the prior only)"
    else:
        res["variant"] = "fitted feedback curve"
    res["status"] = "dry run (shape and leak checks)" if len(info["clean_days"]) < 14 else "fit"
    # backtest table (as daycal.py, offset = honest)
    P, I, E = store.load(); I = I.assign(id=I.id.astype(str))
    C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str); C = C.drop_duplicates("id")
    fo, col = os.environ.get("OFFSET", "results/honest_preds.parquet:honest").split(":")
    O = pd.read_parquet(fo); O["id"] = O.id.astype(str)
    C = C.drop(columns="all").merge(O[["id", col]].drop_duplicates("id").rename(columns={col: "all"}), on="id")
    A = C[["id", "day", "logv", "all"]].merge(I[["id"] + list(RANK.values())], on="id")
    A["mu0"] = np.expm1(A["all"]).clip(lower=0.5); A["y"] = np.expm1(A.logv).clip(lower=0)
    D = A.groupby("day").agg(day_n=("id", "size"), day_lm_sum=("mu0", "sum"), real=("y", "sum")).sort_index()
    D["day_wd"] = pd.to_datetime(D.index).weekday
    D["trail_real7"] = D.real.shift(2).rolling(7, min_periods=3).mean()
    D["trail_lm7"] = D.day_lm_sum.shift(2).rolling(7, min_periods=3).mean()
    A = A.merge(D[COLS], left_on="day", right_index=True)
    a2c = None
    if os.environ.get("A2"):
        X2 = pd.read_parquet(os.environ["A2"]); X2["id"] = X2.id.astype(str)
        A = A.merge(X2[["id", "a2_act14"]], on="id", how="left"); A["a2"] = np.log1p(A.a2_act14.fillna(0)); a2c = "a2"
    dl = os.environ.get("DAYLEVEL")      # the PH agent's out-of-sample day level: day, fold, s_pred (orchestrator split, Nov 3)
    if dl:
        SP = pd.read_parquet(dl)[["day", "s_pred"]]; A = A.merge(SP, on="day", how="left")
        res["day_level"] = f"PH agent s_pred ({dl}); day total = sum(mu0) * exp(s_pred); {int(A.s_pred.notna().groupby(A.day).first().sum())} days"
    else:
        res["day_level"] = "day-calibrated control total (daycal.py terms)"
    A["week"] = pd.to_datetime(A.day).dt.strftime("%G-W%V"); A["mon"] = A.day.str[:7]
    # leak checks
    days = sorted(A.day.unique())
    res["leak_checks"] = {
        "trailing_totals_end": "d-2 (shift(2) on daily totals; final by then)",
        "offset": f"{fo}:{col} (out-of-sample honest launch model)",
        "feedback_curve_days": info["clean_days"],
        "feedback_curve_after_backtest": bool(min(info["clean_days"]) > days[-1]),
        "note_feedback": "the curve is structure (exposure by leaderboard position), fitted on days after the backtest window; it uses no backtest launch's outcome, but in a strict reading it is look-ahead for May-Oct; from the fit date onward it is honest live",
        "line_up_size": "launches on the day's list (known at 00:05 PT when the list is posted)",
        "a2": "dated team comments before launch (optional)" if a2c else "not used (file not provided)"}
    out, alphas = [], {}
    for m in sorted(A.mon.unique()):
        if m < "2026-05":
            continue
        tr, te = A[A.mon < m].copy(), A[A.mon == m].copy()
        raw = lambda Xf: np.mean([lgb.train({"objective": "poisson", "learning_rate": 0.03, "num_leaves": 7, "min_data_in_leaf": 100, "feature_fraction": 1.0,
                                             "bagging_fraction": 0.8, "bagging_freq": 1, "seed": s, "verbose": -1, "num_threads": 8},
                                            lgb.Dataset(tr[COLS], tr.y, init_score=np.log(tr.mu0)), num_boost_round=200).predict(Xf[COLS], raw_score=True)
                                  for s in range(5)], 0)
        te["cal"] = raw(te) + np.log(te.mu0)
        tr["cal"] = raw(tr) + np.log(tr.mu0)                  # in-sample level for choosing alpha on the training months
        def total(gd):
            return float((gd.mu0 * np.exp(gd.s_pred)).sum()) if dl and gd.s_pred.notna().all() else float(np.exp(gd.cal).sum())
        best = None
        BONUS = (1.0, 1.25, 1.5, 2.0, 3.0) if param else (None,)
        for al, bo in [(a_, b_) for a_ in ALPHAS for b_ in BONUS]:
            if param:
                f = np.zeros(20); f[0] = np.log(bo); g = np.zeros(24)
            for be in ((0.0, 0.1, 0.25, 0.5) if a2c else (0.0,)):
                ll = 0.0
                for d, gd in tr[tr.mon >= "2026-04"].groupby("day"):
                    tot = total(gd); sh = shares(gd.mu0, f, g, al, np.exp(be * gd[a2c]) if a2c else None)
                    lam = np.clip(tot * sh, 1e-6, None); ll += float(np.sum(gd.y * np.log(lam) - lam))
                if best is None or ll > best[0]:
                    best = (ll, al, be, bo)
        _, al, be, bo = best; alphas[m] = {"alpha": al, "beta_a2": be, "rank1_bonus": bo}
        if param:
            f = np.zeros(20); f[0] = np.log(bo); g = np.zeros(24)
        te["ds"] = 0.0
        for d, gd in te.groupby("day"):
            te.loc[gd.index, "ds"] = np.log(total(gd) * shares(gd.mu0, f, g, al, np.exp(be * gd[a2c]) if a2c else None))
            te.loc[gd.index, "dl_only"] = np.log(total(gd) * gd.mu0 / gd.mu0.sum())     # day level x prior shares (no curve)
        out.append(te); print("month", m, alphas[m], flush=True)
    T = pd.concat(out); rng = np.random.default_rng(0); res["alpha_by_month"] = alphas
    T["wmon"] = (pd.to_datetime(T.day) - pd.to_timedelta(pd.to_datetime(T.day).dt.weekday, unit="D")).dt.strftime("%Y-%m")
    wmon = T.groupby("week").wmon.first()
    for win, lo in (("May-Oct", "2026-05"), ("Jul-Oct", "2026-07")):
        U = T[T.day >= lo]; r = {}
        for key in ("day", "week", "mon"):
            for k in (3, 5, 10):
                a, b = per_list(U, "cal", key, k), per_list(U, "ds", key, k)
                c_ = per_list(U, "dl_only", key, k)
                line = {"day-calibrated control": round(100 * float(a.mean()), 1), "day strength": round(100 * float(b.mean()), 1), "delta": boot(a, b, rng),
                        "day level x prior shares (no curve)": round(100 * float(c_.mean()), 1), "no-curve delta": boot(a, c_, rng),
                        "honest launch model": round(100 * float(per_list(U, "all", key, k).mean()), 1)}
                if key == "week":
                    dm = (b - a).groupby(wmon.reindex(b.index).values).mean(); line["by month (Monday)"] = {m_: round(100 * float(v), 1) for m_, v in dm.items()}
                if key == "mon":
                    line["by month"] = {m_: [round(100 * float(b[m_]), 1), round(100 * float(a[m_]), 1)] for m_ in b.index if m_ in a.index}
                r[f"{key} top{k}"] = line
        g3 = r["week top3"]["delta"]
        r["gate_passes"] = bool(g3[1] is not None and g3[1][0] > 0)
        res[win] = r
    os.makedirs("results", exist_ok=True)
    json.dump(res, open(f"results/day_strength{'_flat' if os.environ.get('FLAT') else ''}{'_spred' if dl else ''}{'_param' if param else ''}{'_a2' if a2c else ''}.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
