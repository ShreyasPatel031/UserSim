"""Weekly (and monthly) running board with predicted entrants (orchestrator 12:59Z Nov 14). Held data only; counts only.

For each day D of each full week (Mon-Sun PT) in Apr 6 - Oct 25 2026, boards as they would stand right after D's 00:05 forecast:
  (a) current      launches of days < D in the week by votes (what the weekly running board does today)
  (b) predicted    (a) + D's whole line-up inserted at arm 2's predicted final votes (month-forward linear calibration of the backtest
                   prediction to log1p(votes), fitted on earlier months only; April: identity, flagged)
  (b3) top-3 only  (a) + only arm 2's top 3 of D inserted
  (c) oracle       (a) + D's launches at their true final votes
Truth: official weekly_rank <= k (PH's weekly leaderboard, as read by the ranks step; the "first read after Sunday close" is not held for
Apr-Oct, so the final stored weekly_rank is used). Score: |board top k ∩ true weekly top k| / k, k = 3/5/10, by weekday of D;
paired week bootstrap 95% intervals of (b) - (a), (b3) - (a). Monthly: same with monthly_rank, by week-of-month of D (7 months: thin).
Leak notes: votes of days < D are the stored final votes (later reads; day-close votes are not held for Apr-Oct) - this favours (a) and
(b) equally (same earlier-day part). Predictions are the 214-day month-forward arm-2 backtest ('both', 5 seeds). Launches outside the backtest
(LLM 'known', 1.4%) enter (b) at the day's median prediction.
usage: python3 weekly_board_pred.py <X.parquet (tmp/ph_ops/arm2_explain)> <L.parquet (launches)> <out.md>"""
import json, sys
import numpy as np, pandas as pd

X = pd.read_parquet(sys.argv[1])[["id", "day", "mon", "both"]]; X["id"] = X.id.astype(str)
L = pd.read_parquet(sys.argv[2]); L["id"] = L.id.astype(str); OUT = sys.argv[3]
L = L.merge(X[["id", "both"]], on="id", how="left"); L["mon"] = L.day.str[:7]
L["lv"] = np.log1p(L.votes.astype(float))
# month-forward calibration of the prediction to log1p(votes)
L["cal"] = np.nan; cal_info = {}
for m in sorted(L.mon.unique()):
    prev = L[(L.mon < m) & L.both.notna() & (L.mon >= "2026-04")]
    if len(prev) >= 200:
        b, a = np.polyfit(prev.both, prev.lv, 1); cal_info[m] = [round(a, 3), round(b, 3), len(prev)]
    else:
        a, b = 0.0, 1.0; cal_info[m] = "identity (no earlier month)"
    k = L.mon == m; L.loc[k, "cal"] = a + b * L.loc[k, "both"]
L["cal"] = L.cal.fillna(L.groupby("day").cal.transform("median"))
L["pv"] = np.expm1(L.cal)
L["dr3"] = L.groupby("day").cal.rank(ascending=False, method="first") <= 3
L["wk"] = pd.to_datetime(L.day).dt.to_period("W-SUN").apply(lambda p: str(p.start_time.date()))
L["dow"] = pd.to_datetime(L.day).dt.dayofweek
KS = (3, 5, 10)


def hits(board, truth, k):
    return len(set(board.nlargest(k, "v").id) & truth[k]) / k


def run(period_col, rank_col, periods, pos_fn):
    R = []
    for p in periods:
        Z = L[L[period_col] == p]
        truth = {k: set(Z[Z[rank_col] <= k].id) for k in KS}
        for D in sorted(Z.day.unique()):
            prev = Z[Z.day < D].assign(v=lambda z: z.votes.astype(float)); today = Z[Z.day == D]
            B = {"a": prev, "b": pd.concat([prev, today.assign(v=today.pv)]),
                 "b3": pd.concat([prev, today[today.dr3].assign(v=today[today.dr3].pv)]),
                 "c": pd.concat([prev, today.assign(v=today.votes.astype(float))])}
            R.append({"period": p, "day": D, "pos": pos_fn(D), **{f"{n}_{k}": hits(b, truth, k) for n, b in B.items() for k in KS}})
    return pd.DataFrame(R)


def boot(R, x, y, B_=4000, seed=0):
    rng = np.random.default_rng(seed); g = R.groupby("period"); per = g[x].mean() - g[y].mean(); ps = per.index.values
    d = (R[x] - R[y]); dm = d.groupby(R.period).mean()
    bs = [dm.loc[rng.choice(ps, len(ps))].mean() for _ in range(B_)]
    return round(100 * d.mean(), 1), [round(100 * np.percentile(bs, 2.5), 1), round(100 * np.percentile(bs, 97.5), 1)]


weeks = [w for w in sorted(L.wk.unique()) if "2026-04-06" <= w <= "2026-10-19"]   # full weeks inside the backtest (Apr 6 - Oct 25)
RW = run("wk", "weekly_rank", weeks, lambda d: pd.Timestamp(d).day_name()[:3])
months = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
RM = run("mon", "monthly_rank", months, lambda d: f"days {7 * ((int(d[8:]) - 1) // 7) + 1}-{min(7 * ((int(d[8:]) - 1) // 7) + 7, 31)}")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
lines = ["# Weekly board with predicted entrants (held data, Apr 6 - Oct 25 2026)", "",
         f"{len(weeks)} full weeks, {len(RW)} board days; truth = official weekly_rank (final stored read). Hits = share of the board's top k in "
         "the true weekly top k. (a) current board (days < D by votes); (b) + D's line-up at calibrated arm-2 predicted votes; (b3) + only arm 2's "
         "top 3 of D; (c) oracle (D at true final votes). Intervals: paired week bootstrap 95%.", "",
         "Calibration (month-forward, log1p(votes) = a + b x pred): " + json.dumps(cal_info), "",
         "| D | k | (a) | (b) | (b3) | (c) | (b)-(a) [95%] | (b3)-(a) [95%] |", "|---|---|---|---|---|---|---|---|"]
dec = {}
for dn in DAYS + ["all"]:
    R = RW if dn == "all" else RW[RW.pos == dn]
    for k in KS:
        m = {n: round(100 * R[f"{n}_{k}"].mean(), 1) for n in ("a", "b", "b3", "c")}
        d1, ci1 = boot(R, f"b_{k}", f"a_{k}"); d3, ci3 = boot(R, f"b3_{k}", f"a_{k}")
        dec[(dn, k)] = (d1, ci1, d3, ci3)
        lines.append(f"| {dn} | {k} | {m['a']} | {m['b']} | {m['b3']} | {m['c']} | {d1:+} [{ci1[0]:+}, {ci1[1]:+}] | {d3:+} [{ci3[0]:+}, {ci3[1]:+}] |")
lines += ["", "## Monthly (7 months only: intervals are wide and indicative)", "",
          "| D in month | k | (a) | (b) | (b3) | (c) | (b)-(a) [95%] |", "|---|---|---|---|---|---|---|"]
for pn in sorted(RM.pos.unique(), key=lambda s: int(s.split()[1].split("-")[0])) + ["all"]:
    R = RM if pn == "all" else RM[RM.pos == pn]
    for k in KS:
        m = {n: round(100 * R[f"{n}_{k}"].mean(), 1) for n in ("a", "b", "b3", "c")}
        d1, ci1 = boot(R, f"b_{k}", f"a_{k}")
        lines.append(f"| {pn} | {k} | {m['a']} | {m['b']} | {m['b3']} | {m['c']} | {d1:+} [{ci1[0]:+}, {ci1[1]:+}] |")
clear = [f"{dn} top {k}: (b) {v[0]:+} [{v[1][0]:+}, {v[1][1]:+}]" for (dn, k), v in dec.items() if v[1][0] > 0]
clear3 = [f"{dn} top {k}: (b3) {v[2]:+} [{v[3][0]:+}, {v[3][1]:+}]" for (dn, k), v in dec.items() if v[3][0] > 0]
worse = [f"{dn} top {k}: (b) {v[0]:+} [{v[1][0]:+}, {v[1][1]:+}]" for (dn, k), v in dec.items() if v[1][1] < 0]
lines += ["", "## Readout", "", "Weekly cuts where (b) beats (a) with the interval clear of 0: " + ("; ".join(clear) or "none"),
          "", "Weekly cuts where (b3) beats (a) clear of 0: " + ("; ".join(clear3) or "none"),
          "", "Weekly cuts where (b) is worse than (a) clear of 0: " + ("; ".join(worse) or "none"),
          "", "Leak notes: earlier days use stored final votes (day-close votes not held for Apr-Oct; same for (a) and (b)); weekly truth is the "
          "final stored weekly_rank (the first post-Sunday read is not held); April uses identity calibration (no earlier month)."]
open(OUT, "w").write("\n".join(lines) + "\n")
RW.to_csv(OUT.replace(".md", "_days.csv"), index=False)
print("\n".join(lines[-7:]))
