"""WEEKLY-1: structural capture of the weekly and monthly top 10, and where the misses come from. No model calls.

  python -m simharness.weekly1 --bt BT_DIR --launches LAUNCHES_DIR --out OUT.json

BT_DIR: results/structural/backtest/<day>.json for every 2026 day (STRUCT-BT26: arm 3 month-forward, structural_score,
structural_rank, pred_votes = month-forward calibration of score to votes; truth = final daily rank and votes).
LAUNCHES_DIR: the warehouse launches table (weekly_rank, monthly_rank = PH API weeklyRank / monthlyRank; truth only).

Predictions use only the 00:05 structural outputs (score, pred_votes). Ceilings use the day's real outcome.
Decomposition of each real top-10 launch the pred_votes order missed, by two counterfactuals on the same candidates:
  day volume fixed   each launch's pred_votes x (real day total / predicted day total): within-day shares kept
  within-day fixed   predicted day total x (real votes / real day total): day totals kept
  daily order only   the day's predicted vote values handed out in the real daily order (order right, spread as predicted)
A miss is "cross-day" if only the first brings it into the top 10, "within-day" if only the second does, "both" if
either does, "neither" if neither does alone, and "not on the 00:05 line-up" if the launch has no structural file row.
"""
from __future__ import annotations

import argparse
import glob
import json

import numpy as np
import pandas as pd

RNG = np.random.default_rng(0)


def boot(x, B=4000):
    x = np.array([v for v in x if v is not None], float)
    if len(x) < 2:
        return {"mean": float(x.mean()) if len(x) else None, "lo": None, "hi": None, "n": int(len(x))}
    m = RNG.choice(x, (B, len(x))).mean(1)
    return {"mean": round(float(x.mean()), 2), "lo": round(float(np.percentile(m, 2.5)), 2), "hi": round(float(np.percentile(m, 97.5)), 2), "n": int(len(x))}


def load(bt, launches):
    rows = []
    for f in sorted(glob.glob(f"{bt}/*.json")):
        j = json.load(open(f))
        tr = j["truth"].get("by_id") or {}
        for x in j["launches"]:
            t = tr.get(str(x["id"])) or {}
            rows.append({"id": str(x["id"]), "day": j["day"], "score": x.get("structural_score"), "srank": x.get("structural_rank"),
                         "pred_votes": x.get("pred_votes"), "real_rank": t.get("final_rank"), "real_votes": t.get("votes")})
    S = pd.DataFrame(rows)
    L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{launches}/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last")
    L["id"] = L.id.astype(str)
    L["d"] = pd.to_datetime(L.day.astype(str).str[:10])
    return S, L


def topk(df, col, k=10, asc=False, tie=None):
    by = [col] + ([tie[0]] if tie else [])
    ascending = [asc] + ([tie[1]] if tie else [])
    return set(df.sort_values(by, ascending=ascending).id.head(k))


def run(S, L, per):
    rk = "weekly_rank" if per == "week" else "monthly_rank"
    freq = "W-SUN" if per == "week" else "M"
    L = L.dropna(subset=[rk]).copy()
    L["p"] = L.d.dt.to_period(freq).astype(str)
    S = S.copy()
    S["p"] = pd.to_datetime(S.day).dt.to_period(freq).astype(str)
    # day totals over the structural candidates
    S["real_votes_f"] = S.real_votes.astype(float)
    tot = S.groupby("day").agg(pred_tot=("pred_votes", "sum"), real_tot=("real_votes_f", "sum")).reset_index()
    S = S.merge(tot, on="day")
    S["cf_dayfix"] = S.pred_votes * S.real_tot / S.pred_tot            # cross-day error removed
    S["cf_withinfix"] = S.pred_tot * S.real_votes_f / S.real_tot       # within-day error removed
    # order only: the day's predicted vote values, handed out in the real daily order (spread of the day kept as predicted)
    S["cf_orderfix"] = np.nan
    for d, g in S.dropna(subset=["pred_votes", "real_rank"]).groupby("day"):
        vals = np.sort(g.pred_votes.to_numpy())[::-1]
        S.loc[g.sort_values(["real_rank", "real_votes_f"], ascending=[True, False]).index, "cf_orderfix"] = vals
    per_rows, misses = [], []
    for p, g in L.groupby("p"):
        truth = set(g[g[rk] <= 10].id)
        pp = pd.Period(p, freq)
        if len(truth) != 10 or pp.start_time < pd.Timestamp("2026-01-01") or pp.end_time > pd.Timestamp(S.day.max()) + pd.Timedelta(days=1):
            continue   # only periods inside the files' range and already closed
        C = S[S.p == p].dropna(subset=["pred_votes"])
        days_in = pd.period_range(pd.Period(p, freq).start_time, pd.Period(p, freq).end_time, freq="D")
        r = {"period": p, "days_in_period": len(days_in), "days_with_file": C.day.nunique(), "candidates": len(C),
             "truth_on_lineup": len(truth & set(C.id))}
        pv = topk(C, "pred_votes")
        r["cap_pred_votes"] = len(pv & truth) * 10
        r["cap_score"] = len(topk(C, "score") & truth) * 10
        r["ceil_real_votes"] = len(topk(C.dropna(subset=["real_votes_f"]), "real_votes_f") & truth) * 10
        r["ceil_real_daily_rank"] = len(topk(C.dropna(subset=["real_rank"]), "real_rank", asc=True, tie=("real_votes_f", False)) & truth) * 10
        dayfix = topk(C.dropna(subset=["cf_dayfix"]), "cf_dayfix")
        withinfix = topk(C.dropna(subset=["cf_withinfix"]), "cf_withinfix")
        r["cap_if_day_volume_fixed"] = len(dayfix & truth) * 10
        r["cap_if_within_day_fixed"] = len(withinfix & truth) * 10
        r["cap_if_daily_order_fixed_only"] = len(topk(C.dropna(subset=["cf_orderfix"]), "cf_orderfix") & truth) * 10
        per_rows.append(r)
        cid = set(C.id)
        for i in truth - pv:
            if i not in cid:
                kind = "not on the 00:05 line-up"
                row = {}
            else:
                a, b = i in dayfix, i in withinfix
                kind = "both" if a and b else "cross-day" if a else "within-day" if b else "neither"
                x = C[C.id == i].iloc[0]
                row = {"srank": x.srank, "real_rank": x.real_rank, "pred_tot": round(x.pred_tot), "real_tot": round(x.real_tot),
                       "day_ratio_real_over_pred": round(x.real_tot / x.pred_tot, 3)}
            misses.append({"period": p, "id": i, "kind": kind, **row})
    R = pd.DataFrame(per_rows)
    M = pd.DataFrame(misses)
    full = R[R.days_with_file == R.days_in_period]
    out = {"periods": len(R), "periods_every_day_on_file": len(full),
           "metrics": {k: boot(R[k]) for k in ("cap_pred_votes", "cap_score", "ceil_real_votes", "ceil_real_daily_rank",
                                               "cap_if_day_volume_fixed", "cap_if_within_day_fixed", "cap_if_daily_order_fixed_only")},
           "truth_on_lineup_share": round(float(R.truth_on_lineup.sum() / (10 * len(R))), 4),
           "misses": int(len(M)),
           "miss_kinds": {k: {"n": int(v), "share": round(v / len(M), 4)} for k, v in M.kind.value_counts().items()} if len(M) else {},
           "missed_on_lineup": {}}
    on = M[M.kind != "not on the 00:05 line-up"] if len(M) else M
    if len(on):
        out["missed_on_lineup"] = {"n": int(len(on)), "median_daily_structural_rank": float(on.srank.median()),
                                   "share_daily_structural_rank_le3": round(float((on.srank <= 3).mean()), 4),
                                   "share_daily_structural_rank_4_10": round(float(((on.srank > 3) & (on.srank <= 10)).mean()), 4),
                                   "share_daily_structural_rank_gt10": round(float((on.srank > 10).mean()), 4),
                                   "median_real_daily_rank": float(on.real_rank.median()),
                                   "median_day_ratio_real_over_pred": float(on.day_ratio_real_over_pred.median()),
                                   "share_day_underpredicted_10pct": round(float((on.day_ratio_real_over_pred > 1.1).mean()), 4)}
    out["rows"] = R.to_dict("records")
    out["miss_rows"] = M.to_dict("records")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bt", required=True)
    ap.add_argument("--launches", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    S, L = load(a.bt, a.launches)
    res = {"version": "weekly1_v1", "days": int(S.day.nunique()), "launches": int(len(S)),
           "week": run(S, L, "week"), "month": run(S, L, "month")}
    json.dump(res, open(a.out, "w"), indent=1, default=str)
    for per in ("week", "month"):
        r = res[per]
        print(per, json.dumps({k: v for k, v in r.items() if k not in ("rows", "miss_rows")}, indent=1, default=str))


if __name__ == "__main__":
    main()
