"""WEEKLY-2: an in-week forecast of the weekly / monthly top 10 (finished days' real votes known), and late votes.
No model calls.

  python -m simharness.weekly2 --work WORK [--sync gs://.../tmp/weekly2]

WORK (local, private):
  bt/<day>.json          STRUCT-BT26 (pred_votes at 00:05; truth votes = the warehouse vote total, read long after the day)
  launches/*.parquet     warehouse launches (weekly_rank / monthly_rank truth; votes; updated_at)
  vs/*.parquet           tables/vote_snapshots (hourly votes and comments during the launch day; Oct 31 - Nov 25)
  wc/*.jsonl             raw/ph_at_launch/<day>/weekly_close/*.jsonl (official API votesCount and weeklyRank after the week)

Part 1. For each weekday d (Mon=0 .. Sun=6) of the 44 closed 2026 weeks: launches of days before d carry their real
  votes, the rest carry pred_votes; the top 10 of that mix against the real weekly top 10. Monthly: the same with the cut
  at the start of week k of the month (day 1, 8, 15, 22, 29). The "real votes" of finished days are the warehouse totals,
  read weeks to months later: they include late votes a forecaster mid-week would not yet see (an upper bound; part 2
  measures how much that matters).
Part 2. Late votes on the Nov launches with launch-day snapshots: launch-day close = the last snapshot of the launch
  day (hour >= 22); week total = the first weekly_close read after the week; later total = the warehouse total read
  Nov 25. Late share, its spread, by real daily rank, and how predictable it is (leave-one-day-out R^2 of
  log(week total / day close) on 00:05 fields and on launch-day results). Weekly capture on the weeks with day-close
  votes for every day: day-close votes alone, day-close plus predicted late votes, week totals.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess

import numpy as np
import pandas as pd

RNG = np.random.default_rng(0)


def boot(x, B=4000):
    x = np.array([v for v in x if v is not None and not np.isnan(v)], float)
    if len(x) < 2:
        return {"mean": float(x.mean()) if len(x) else None, "lo": None, "hi": None, "n": int(len(x))}
    m = RNG.choice(x, (B, len(x))).mean(1)
    return {"mean": round(float(x.mean()), 2), "lo": round(float(np.percentile(m, 2.5)), 2), "hi": round(float(np.percentile(m, 97.5)), 2), "n": int(len(x))}


def load(W):
    rows = []
    for f in sorted(glob.glob(f"{W}/bt/*.json")):
        j = json.load(open(f))
        tr = j["truth"].get("by_id") or {}
        for x in j["launches"]:
            t = tr.get(str(x["id"])) or {}
            rows.append({"id": str(x["id"]), "day": j["day"], "score": x.get("structural_score"), "srank": x.get("structural_rank"),
                         "pred_votes": x.get("pred_votes"), "real_rank": t.get("final_rank"), "votes": t.get("votes")})
    S = pd.DataFrame(rows)
    S["votes"] = S.votes.astype(float)
    L = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{W}/launches/*.parquet")]).sort_values("updated_at").drop_duplicates("id", keep="last")
    L["id"] = L.id.astype(str)
    L["d"] = pd.to_datetime(L.day.astype(str).str[:10])
    return S, L


def closed_periods(L, rk, freq, last_day):
    L = L.dropna(subset=[rk]).copy()
    L["p"] = L.d.dt.to_period(freq).astype(str)
    out = {}
    for p, g in L.groupby("p"):
        pp = pd.Period(p, freq)
        truth = set(g[g[rk] <= 10].id)
        if len(truth) == 10 and pp.start_time >= pd.Timestamp("2026-01-01") and pp.end_time <= pd.Timestamp(last_day) + pd.Timedelta(days=1):
            out[p] = truth
    return out


def top10(C, col):
    return set(C.sort_values(col, ascending=False).id.head(10))


# ------------------------------------------------------------------ part 1
def part1(S, L):
    last = S.day.max()
    S = S.dropna(subset=["pred_votes"]).copy()
    S["dt"] = pd.to_datetime(S.day)
    res = {}
    for per, rk, freq in (("week", "weekly_rank", "W-SUN"), ("month", "monthly_rank", "M")):
        P = closed_periods(L, rk, freq, last)
        S["p"] = S.dt.dt.to_period(freq).astype(str)
        cuts = range(8) if per == "week" else [1, 8, 15, 22, 29, 32]
        curve = {}
        for c in cuts:
            caps = []
            for p, truth in P.items():
                C = S[S.p == p].copy()
                start = pd.Period(p, freq).start_time
                cut = start + pd.Timedelta(days=c if per == "week" else c - 1)
                known = C.dt < cut
                C["mix"] = np.where(known & C.votes.notna(), C.votes, C.pred_votes)
                caps.append(len(top10(C, "mix") & truth) * 10)
            lab = (["Mon 00:05", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "after Sun (all real)"][c] if per == "week"
                   else {1: "day 1 (all predicted)", 8: "day 8", 15: "day 15", 22: "day 22", 29: "day 29", 32: "after month end (all real)"}[c])
            curve[lab] = boot(caps)
        res[per] = {"periods": len(P), "capture_by_cut": curve}
    return res


# ------------------------------------------------------------------ part 2
def day_close(W):
    V = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{W}/vs/*.parquet")]).drop_duplicates(["launch_id", "at"])
    V = V[V.hours_since_start >= 22]
    V = V.sort_values("hours_since_start").groupby("launch_id").tail(1)
    return {str(i): (float(v), float(c), d) for i, v, c, d in zip(V.launch_id, V.votes, V.comments, V.day)}


def week_close(W):
    """First read after each week: {id: (votesCount, weeklyRank, week)}."""
    reads = {}
    for f in sorted(glob.glob(f"{W}/wc/*.jsonl")):
        r = [json.loads(l) for l in open(f)]
        h = r[0]
        if h["week_pt"] not in reads:
            reads[h["week_pt"]] = (h, r[1:])
    out = {}
    for wk, (h, rows) in reads.items():
        for x in rows:
            if x.get("votesCount") is not None:
                out[str(x["id"])] = (float(x["votesCount"]), x.get("weeklyRank"), wk, h["fetched_at"])
    return out, {wk: h["fetched_at"] for wk, (h, _) in reads.items()}


def part2(W, S, L):
    DC = day_close(W)
    WC, reads = week_close(W)
    Lnow = L[L.updated_at.astype(str) >= "2026-11-25"].set_index("id").votes.to_dict()
    T = S[S.id.isin(DC)].copy()
    T["dc_votes"] = T.id.map(lambda i: DC[i][0])
    T["dc_comments"] = T.id.map(lambda i: DC[i][1])
    T["week_votes"] = T.id.map(lambda i: WC[i][0] if i in WC else np.nan)
    T["now_votes"] = T.id.map(lambda i: float(Lnow[i]) if i in Lnow else np.nan)
    T["dow"] = pd.to_datetime(T.day).dt.dayofweek
    T["days_left_in_week"] = 6 - T.dow
    T["age_at_nov25"] = (pd.Timestamp("2026-11-25") - pd.to_datetime(T.day)).dt.days
    T["late_share_week"] = 1 - T.dc_votes / T.week_votes
    T["late_share_now"] = 1 - T.dc_votes / T.now_votes
    T["rank_bucket"] = pd.cut(T.real_rank, [0, 1, 3, 10, 1000], labels=["1", "2-3", "4-10", ">10"])
    out = {"launches_with_day_close": int(len(T)), "days": int(T.day.nunique()), "week_close_reads": reads,
           "with_week_total": int(T.week_votes.notna().sum()), "with_nov25_total": int(T.now_votes.notna().sum())}
    q = lambda x: {f"p{p}": round(float(np.nanpercentile(x, p)), 4) for p in (10, 25, 50, 75, 90)} if np.isfinite(x).sum() else {}
    for col in ("late_share_week", "late_share_now"):
        G = T.dropna(subset=[col])
        out[col] = {"n": int(len(G)), "dist": q(G[col]),
                    "by_real_daily_rank": {str(k): {"n": int(len(g)), "median": round(float(g[col].median()), 4)} for k, g in G.groupby("rank_bucket", observed=True)},
                    "by_days_left_in_week": {int(k): round(float(g[col].median()), 4) for k, g in G.groupby("days_left_in_week")} if col == "late_share_week" else None}
    # predictability of log(week total / day close)
    G = T.dropna(subset=["week_votes"]).copy()
    G = G[G.dc_votes > 0]
    G["y"] = np.log(G.week_votes / G.dc_votes)
    sets = {"00:05 fields": ["score", "days_left_in_week"],
            "launch-day results": ["log_dc_votes", "log_dc_comments", "real_rank", "days_left_in_week"],
            "both": ["score", "log_dc_votes", "log_dc_comments", "real_rank", "days_left_in_week"]}
    G["log_dc_votes"] = np.log1p(G.dc_votes)
    G["log_dc_comments"] = np.log1p(G.dc_comments)
    r2 = {}
    preds = {}
    for nm, cols in sets.items():
        H = G.dropna(subset=cols + ["y"])
        yhat = np.zeros(len(H))
        for d in H.day.unique():
            tr, te = H.day != d, H.day == d
            X = np.c_[np.ones(tr.sum()), H.loc[tr, cols].to_numpy(float)]
            b, *_ = np.linalg.lstsq(X, H.loc[tr, "y"].to_numpy(float), rcond=None)
            yhat[te.to_numpy()] = np.c_[np.ones(te.sum()), H.loc[te, cols].to_numpy(float)] @ b
        r2[nm] = {"n": int(len(H)), "loo_day_r2": round(float(1 - np.sum((H.y - yhat) ** 2) / np.sum((H.y - H.y.mean()) ** 2)), 4)}
        preds[nm] = dict(zip(H.id, yhat))
    out["predict_log_week_over_dayclose"] = r2
    # capture on weeks whose every day has day-close votes and a week-close read
    truthW = closed_periods(L, "weekly_rank", "W-SUN", S.day.max())
    caps = []
    for wk in reads:
        a, b = wk.split("..")
        p = str(pd.Period(a, "W-SUN"))
        truth = truthW.get(p)
        days = [str(x.date()) for x in pd.date_range(a, b)]
        C = T[T.day.isin(days)].copy()
        full_days = all(d in set(C.day) for d in days)
        if truth is None:
            continue
        C["dc_plus_late"] = C.dc_votes * np.exp(C.id.map(preds["both"]).fillna(G.y.mean()))
        C["dc_plus_mean_late"] = C.dc_votes * np.exp(C.days_left_in_week.map(G.groupby("days_left_in_week").y.mean()).fillna(G.y.mean()))
        caps.append({"week": wk, "every_day_has_day_close": full_days, "launches": int(len(C)),
                     "cap_day_close_votes": len(top10(C, "dc_votes") & truth) * 10,
                     "cap_day_close_plus_mean_late_by_weekday": len(top10(C, "dc_plus_mean_late") & truth) * 10,
                     "cap_day_close_plus_predicted_late": len(top10(C, "dc_plus_late") & truth) * 10,
                     "cap_week_total_votes": len(top10(C.dropna(subset=["week_votes"]), "week_votes") & truth) * 10,
                     "cap_warehouse_total_votes": len(top10(C.dropna(subset=["votes"]), "votes") & truth) * 10,
                     "cap_structural_pred_votes": len(top10(C, "pred_votes") & truth) * 10})
    out["weekly_capture_weeks_with_close"] = caps
    return out, T


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--sync")
    a = ap.parse_args(argv)
    S, L = load(a.work)
    res = {"version": "weekly2_v1", "part1": part1(S, L)}
    res["part2"], T = part2(a.work, S, L)
    os.makedirs(f"{a.work}/out", exist_ok=True)
    json.dump(res, open(f"{a.work}/out/weekly2.json", "w"), indent=1, default=str)
    T.to_parquet(f"{a.work}/out/late_votes_rows.parquet", index=False)
    if a.sync:
        subprocess.run(["gsutil", "-q", "-m", "cp", f"{a.work}/out/*", a.sync + "/"], check=False)
    print(json.dumps(res, indent=1, default=str)[:15000])


if __name__ == "__main__":
    main()
