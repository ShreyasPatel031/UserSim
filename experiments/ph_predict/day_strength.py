"""Weekly-board magnitude model (orchestrator, Nov 3): predict each day's vote pool pre-launch, so launches can be
ranked across days, and test it on the weekly / monthly boards against the honest day-calibrated control.

Reference: the honest launch model (HONEST_PREDS, column HONEST_COL; default "honest - live set", the live forecast's
honest set) with userbase_eval's day-calibrated control (offset Poisson LightGBM, day terms only, rolling monthly, 5
seeds). Same folds and seeds here.

Day strength. Per day: s = log(real total votes) - log(sum of the honest model's expected votes) (how much bigger or
smaller the day's pool is than the launch model's level). Predicted pre-launch from day terms only, fit by ridge on
earlier months (rolling monthly, like the control):
  weekday (one-hot), US federal holiday, days to / from the nearest holiday (capped at 7), log line-up size, log of the
  line-up's predicted total, trailing 7-day real and predicted totals ending day-2 (final by then; log), and their gap.
Final daily totals are used (Jul-Oct and earlier); hourly snapshots are not needed for this fit (clean hourly days are
too few, ~14 by Nov 16).
Arms (each launch: log expected votes):
  raw       the honest launch model, no day level
  control   the day-calibrated control (userbase_eval.fit_boards)
  strength  honest + predicted s (launch magnitude = launch score x predicted day strength)
  blend     control + ridge-predicted residual day level of the control (does the explicit day model add to it?)
Gate first (day level, out of sample): Spearman over days of predicted vs actual s, and the same for the control's
implied day level (log control day total - log honest day total); paired bootstrap over days of the difference.
Boards: weekly (paired by week) and monthly (labelled too few lists) top 3/5/10, each arm vs the control, plus daily as
a check (strength and blend move whole days together, so daily order is unchanged by construction).
usage: SIMLAB_DATA=data_v2 HONEST_PREDS=... python day_strength.py -> results/day_strength.json"""
import json, os
import numpy as np, pandas as pd
import userbase_eval as UE

OUT = os.environ.get("OUT", "results/day_strength.json")
PRED_OUT = os.environ.get("PRED_OUT", "results/day_strength_pred.parquet")   # day, s_pred, fold


def holidays(days):
    from pandas.tseries.holiday import USFederalHolidayCalendar
    d = pd.to_datetime(pd.Series(sorted(days)))
    lo, hi = d.min() - pd.Timedelta(days=30), d.max() + pd.Timedelta(days=30)
    H = USFederalHolidayCalendar().holidays(lo, hi)   # observed dates; also flag the actual fixed dates (Jul 4 on a Saturday)
    fixed = pd.to_datetime([f"{y}-{md}" for y in range(lo.year, hi.year + 1) for md in ("01-01", "06-19", "07-04", "11-11", "12-25")])
    H = H.union(fixed[(fixed >= lo) & (fixed <= hi)])
    is_h = d.isin(H).astype(float)
    to = d.map(lambda x: min([(h - x).days for h in H if h >= x] or [99])).clip(upper=7)
    since = d.map(lambda x: min([(x - h).days for h in H if h <= x] or [99])).clip(upper=7)
    return pd.DataFrame({"hol": is_h.values, "to_hol": to.values, "since_hol": since.values}, index=d.dt.strftime("%Y-%m-%d"))


def day_table(A):
    D = A.groupby("day").agg(n=("id", "size"), lm=("mu0", "sum"), real=("y", "sum"), mon=("mon", "first")).sort_index()
    D["s"] = np.log(D.real.clip(lower=1)) - np.log(D.lm)
    D["wd"] = pd.to_datetime(D.index).dayofweek
    D["log_n"] = np.log(D.n); D["log_lm"] = np.log(D.lm)
    D["tr_real"] = np.log(D.real.shift(2).rolling(7, min_periods=3).mean())
    D["tr_lm"] = np.log(D.lm.shift(2).rolling(7, min_periods=3).mean())
    D["tr_gap"] = D.tr_real - D.tr_lm
    D = D.join(holidays(D.index))
    for w in range(7):
        D[f"wd{w}"] = (D.wd == w).astype(float)
    return D


XCOLS = [f"wd{w}" for w in range(7)] + ["hol", "to_hol", "since_hol", "log_n", "log_lm", "tr_real", "tr_lm", "tr_gap"]


def leak_check(A, D, days, n=40, seed=0):
    """Each day's inputs may use only votes final before it: recompute day d's row with every real total from d-1 on
    hidden (votes of launches on days >= d-1 set to NaN) and assert XCOLS are unchanged."""
    rng = np.random.default_rng(seed)
    for d_ in map(str, rng.choice(sorted(days), min(n, len(days)), replace=False)):
        cut = (pd.Timestamp(d_) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        with np.errstate(divide="ignore"):   # hidden days' targets are log(0); they are not inputs
            Dm = day_table(A.assign(y=A.y.where(A.day < cut)))
        a, b = D.loc[d_, XCOLS].astype(float), Dm.loc[d_, XCOLS].astype(float)
        assert np.allclose(a.fillna(-9e9), b.fillna(-9e9)), f"leak: day {d_} inputs use votes from {cut} on: {(a - b)[a.ne(b)].to_dict()}"
    return True


def ridge(tr, te, y, cols, lam=5.0):
    X = tr[cols].fillna(tr[cols].mean()); Xt = te[cols].fillna(tr[cols].mean())
    mu, sd = X.mean(), X.std().replace(0, 1)
    Z = np.c_[np.ones(len(X)), (X - mu) / sd]; Zt = np.c_[np.ones(len(Xt)), (Xt - mu) / sd]
    P = lam * np.eye(Z.shape[1]); P[0, 0] = 0
    w = np.linalg.solve(Z.T @ Z + P, Z.T @ y)
    return Zt @ w


def main():
    rng = np.random.default_rng(0)
    A = UE.day_terms(UE.honest())
    T = UE.fit_boards(A, [], seeds=int(os.environ.get("SEEDS", "5")))   # control (and an unused linear arm) per test month
    T["raw"] = np.log(T.mu0)
    D = day_table(A)
    # the control's implied day level, per day: log(sum of control expected votes) - log(honest day total)
    cd = T.assign(ec=np.exp(T.control)).groupby("day").agg(ec=("ec", "sum"), lm=("mu0", "sum"))
    D["s_control"] = np.log(cd.ec) - np.log(cd.lm)
    pred = {}
    for m in sorted(T.mon.unique()):
        tr, te = D[D.mon < m].dropna(subset=["s"]), D[D.mon == m]
        tr = tr[tr.tr_real.notna()]
        if len(tr) < 30:
            continue
        ps = ridge(tr, te, tr.s.values, XCOLS)
        # blend: the control's remaining day-level error on earlier months (needs the control's level there: only
        # months already tested have it)
        trc = tr[tr.s_control.notna()]
        pb = ridge(trc, te, (trc.s - trc.s_control).values, XCOLS) if len(trc) >= 30 else np.zeros(len(te))
        for d_, a, b in zip(te.index, ps, pb):
            pred[d_] = (a, b)
    D["s_pred"] = D.index.map(lambda d_: pred.get(d_, (np.nan, np.nan))[0])
    D["blend_adj"] = D.index.map(lambda d_: pred.get(d_, (np.nan, np.nan))[1])
    T = T[T.day.isin([d_ for d_ in pred])].copy()
    T["strength"] = T.raw + T.day.map(D.s_pred)
    T["blend"] = T.control + T.day.map(D.blend_adj)
    # pre-launch only: day inputs use votes final before each day (d-2 trailing), and each launch's weekly score is
    # its own launch score + its day's predicted level (no realized total of any day, same week or not)
    leak_check(A, D, list(pred))
    assert np.allclose(T.strength - T.raw, T.day.map(D.s_pred)) and not np.allclose(T.strength, T.day.map(np.log(D.real.clip(lower=1))))

    # gate: day level, out of sample
    G = D.loc[[d_ for d_ in pred]].dropna(subset=["s", "s_pred", "s_control"])
    from scipy.stats import spearmanr
    days = G.index.values
    def rho(idx, col):
        S = G.loc[idx]; return spearmanr(S[col], S.s).correlation
    bs = []
    for _ in range(5000):
        i = rng.choice(days, len(days))
        bs.append((rho(i, "s_pred"), rho(i, "s_control"), rho(i, "s_pred") - rho(i, "s_control")))
    bs = np.array(bs)
    ci = lambda k: [round(float(x), 3) for x in np.nanpercentile(bs[:, k], [2.5, 97.5])]
    res = {"leak_check": "passed (40 days: inputs unchanged with votes from d-1 on hidden)", "reference": os.environ.get("HONEST_COL", "honest") + " with the day-calibrated control (userbase_eval)",
           "days_tested": int(len(G)), "months_tested": sorted(T.mon.unique()),
           "gate": {"spearman_day_level_strength": [round(float(rho(days, "s_pred")), 3), ci(0)],
                    "spearman_day_level_control": [round(float(rho(days, "s_control")), 3), ci(1)],
                    "strength_minus_control": [round(float(rho(days, "s_pred") - rho(days, "s_control")), 3), ci(2)],
                    "mae_day_level": {"strength": round(float((G.s_pred - G.s).abs().mean()), 3),
                                      "control": round(float((G.s_control - G.s).abs().mean()), 3)}}}
    wk_mon = T.groupby("week").day.min().str[:7]
    boards = {}
    for key in ("week", "mon", "day"):
        for k in (3, 5, 10):
            c = UE.per_list(T, "control", key, k); line = {"lists": int(len(c)), "control": round(100 * float(c.mean()), 1) if len(c) else None}
            for arm in ("raw", "strength", "blend"):
                a = UE.per_list(T, arm, key, k); ks = c.index.intersection(a.index)
                line[arm] = round(100 * float(a[ks].mean()), 1) if len(ks) else None
                line[f"{arm} - control"] = UE.boot(((a[ks] - c[ks]) * 100).values, rng)
            if key == "week":
                mo = pd.Series([wk_mon[x] for x in c.index], index=c.index)
                s_ = UE.per_list(T, "strength", key, k).reindex(c.index)
                line["strength - control by month"] = {m_: round(float(v), 1) for m_, v in ((s_ - c) * 100).groupby(mo.values).mean().items()}
            if key == "mon":
                line["note"] = "too few lists for a conclusion"
            boards[f"{key} top{k}"] = line
    res["boards"] = boards
    # out-of-sample per-day day level for E5's launch-level curve (combined arm later): fold = the test month (ridge fit
    # on earlier months only). No launch or person data.
    P_ = D.loc[[d_ for d_ in pred], ["mon", "s_pred"]].rename(columns={"mon": "fold"}).rename_axis("day").reset_index()
    P_.to_parquet(PRED_OUT, index=False); res["day_predictions"] = {"file": PRED_OUT, "days": int(len(P_))}
    json.dump(res, open(OUT, "w"), indent=1)
    print(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    main()
