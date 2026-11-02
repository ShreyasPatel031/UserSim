"""Day-level calibration of the launch model for the weekly and monthly boards (pre-launch only). The launch model ranks
launches within a day well, but its level across days is off: busy or quiet days, weekdays. Model: Poisson LightGBM on
final votes with log(launch model's expected votes) as the offset and day terms only, so a day's launches move
together and the daily order cannot change:
  day_wd         weekday
  day_n          line-up size
  day_lm_sum     sum of the launch model's expected votes over the line-up
  trail_real7    mean daily total of real votes over the 7 days ending 2 days before (final by then)
  trail_lm7      the same days' launch-model totals (so the model can learn how far off the level runs)
Rolling monthly (train on earlier months, from Apr), 5 seeds. Weekly / monthly top 3/5/10 vs the launch model, paired
bootstrap over lists (10,000), wins per month (weekly lists by the month of their Monday), on May-Oct and Jul-Oct.
EXTRA=<file in data/> (e.g. cmp_features_ph): also fit day terms + that file's inputs (NaN where missing) and report it
against the day-calibrated control, on daily and weekly lists, with the file's coverage.
usage: SIMLAB_DATA=data_v2 [EXTRA=cmp_features_ph] python daycal.py -> results/daycal[_<EXTRA>].json"""
import json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from simlab import store

RANK = {"week": "out_weeklyRank", "mon": "out_monthlyRank", "day": "out_dailyRank"}
COLS = ["day_wd", "day_n", "day_lm_sum", "trail_real7", "trail_lm7"]


def per_list(T, col, key, k):
    return pd.Series({g_: len(set(g.nlargest(k, col).id) & set(g[g[RANK[key]] <= k].id)) / k for g_, g in T.groupby(key) if (g[RANK[key]] <= k).sum() == k})


def boot(a, b, rng):
    ks = a.index.intersection(b.index); d = (b[ks] - a[ks]).values
    if len(d) < 2:
        return [round(100 * float(d.mean()), 1) if len(d) else None, None, int(len(d))]
    bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(10000)]
    return [round(100 * float(d.mean()), 1), [round(100 * float(x), 1) for x in np.percentile(bs, [2.5, 97.5])], int(len(d))]


def main():
    P, I, E = store.load(); I = I.assign(id=I.id.astype(str))
    C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str); C = C.drop_duplicates("id")
    A = C[["id", "day", "logv", "all"]].merge(I[["id"] + list(RANK.values())], on="id")
    A["mu0"] = np.expm1(A["all"]).clip(lower=0.5); A["y"] = np.expm1(A.logv).clip(lower=0)
    D = A.groupby("day").agg(day_n=("id", "size"), day_lm_sum=("mu0", "sum"), real=("y", "sum")).sort_index()
    D["day_wd"] = pd.to_datetime(D.index).weekday
    D["trail_real7"] = D.real.shift(2).rolling(7, min_periods=3).mean()
    D["trail_lm7"] = D.day_lm_sum.shift(2).rolling(7, min_periods=3).mean()
    A = A.merge(D[COLS], left_on="day", right_index=True)
    EXTRA = os.environ.get("EXTRA"); xc = []
    if EXTRA:
        K = pd.DataFrame.from_dict(json.load(open(f"data/{EXTRA}.json")), orient="index").rename_axis("id").reset_index()
        xc = [c for c in K if c != "id"]; A = A.merge(K, on="id", how="left")
    A["week"] = pd.to_datetime(A.day).dt.strftime("%G-W%V"); A["mon"] = A.day.str[:7]
    A["wmon"] = (pd.to_datetime(A.day) - pd.to_timedelta(pd.to_datetime(A.day).dt.weekday, unit="D")).dt.strftime("%Y-%m")
    out = []
    for m in sorted(A.mon.unique()):
        if m < "2026-05":
            continue
        tr, te = A[A.mon < m], A[A.mon == m].copy()
        for name, cols in (("cal", COLS), ("cal_x", COLS + xc)) if xc else (("cal", COLS),):
            raw = np.mean([lgb.train({"objective": "poisson", "learning_rate": 0.03, "num_leaves": 7, "min_data_in_leaf": 100, "feature_fraction": 1.0,
                                      "bagging_fraction": 0.8, "bagging_freq": 1, "seed": s, "verbose": -1, "num_threads": 8},
                                     lgb.Dataset(tr[cols], tr.y, init_score=np.log(tr.mu0)), num_boost_round=200).predict(te[cols], raw_score=True)
                           for s in range(5)], 0)
            te[name] = raw + np.log(te.mu0)
        out.append(te)
    T = pd.concat(out); rng = np.random.default_rng(0)
    wmon = T.groupby("week").wmon.first()
    res = {"launches": len(T), "days": int(T.day.nunique()), "inputs": COLS}
    for win, lo in (("May-Oct", "2026-05"), ("Jul-Oct", "2026-07")):
        U = T[T.day >= lo]; r = {}
        for key in ("day", "week", "mon"):
            for k in (3, 5, 10):
                a, b = per_list(U, "all", key, k), per_list(U, "cal", key, k)
                line = {"launch model": round(100 * float(a.mean()), 1), "calibrated": round(100 * float(b.mean()), 1), "delta": boot(a, b, rng)}
                if key == "week":
                    dm = (b - a).groupby(wmon.reindex(b.index).values).mean()
                    line["by month (Monday)"] = {m_: round(100 * float(v), 1) for m_, v in dm.items()}
                if key == "mon":
                    line["by month"] = {m_: round(100 * float(b[m_] - a[m_]), 1) for m_ in b.index}
                if xc:
                    c2 = per_list(U, "cal_x", key, k)
                    line[f"day-calibrated + {EXTRA}"] = round(100 * float(c2.mean()), 1)
                    line["extra vs day-calibrated"] = boot(b, c2, rng); line["extra vs launch model"] = boot(a, c2, rng)
                r[f"{key} top{k}"] = line
        if xc:
            r["coverage (launches with the extra inputs)"] = round(float(U[xc[0]].notna().mean()), 3)
        res[win] = r
    json.dump(res, open(f"results/daycal{'_' + EXTRA if EXTRA else ''}.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
