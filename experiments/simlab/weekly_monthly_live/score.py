"""Weekly / monthly north-star cuts scored live (orchestrator 09:33Z Nov 17). Counts and launch ids only.

Periods: PH weeks are Mon-Sun PT (period_parts.period): the closed week is Nov 9-15 (close Sun Nov 15 23:59 PT); the one before is
Nov 2-8. Month: October 2026.
Truth: results/web/truth_weekly.json / truth_monthly.json (first warehouse part after the close holding every day of the period and a
non-null weekly / monthly rank; period_parts.truth).
Lines, each scored at call points c (top 3 / 5 / 10 overlap with the final period top k; ceiling = truth top-k launches already
known at the call):
  board_votes_only / board_with_entrants   the live period_writer files (tmp/e5/website/probabilities/<D>_weekly.json, written
                                           D+1 ~01:20 PT; call = D+1 00:05 + 75 min); replay rows from period_parts.board where no
                                           live file (flag 'replay', never pooled with live).
  weekly_live:<point>                      the other writer's results/weekly_live files; scored only when written before the close.
  sum_published                            ex-ante: every launch of the period up to the call day ranked by its own published 00:05
                                           arm-2 prediction (raw/daily/<d>/forecast_<d>.parquet 'pred', log votes). No votes used.
  sum_arm2_rebuild / sum_arm3_rebuild      the same with the month-forward rebuild predictions (mna/out/arm3_oos_contrib.parquet
                                           pred2 / pred3; Apr 1 - Nov 12 only).
Backtest of the ex-ante sums over every week / month with full rebuild coverage (Apr-Oct): week-bootstrap intervals.
    python score.py <scratchpad>
"""
import glob, json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
SP = sys.argv[1]; W = f"{SP}/wm"; PT = "America/Los_Angeles"; K = (3, 5, 10); rng = np.random.default_rng(0)

TW = json.load(open(f"{W}/truth_weekly.json"))["periods"]; TM = json.load(open(f"{W}/truth_monthly.json"))["periods"]
def truth(per, start):
    p = (TW if per == "week" else TM).get(start)
    if not p or p.get("status") != "ok": return None, p
    r = pd.Series(p["ranks"]).astype(int); return {k: set(r[r <= k].index) for k in K}, p

# predictions
pub = []
for f in sorted(glob.glob(f"{W}/fc/forecast_*.parquet")):
    x = pd.read_parquet(f, columns=["id", "day", "pred"]); x["id"] = x.id.astype(str); pub.append(x)
PUB = pd.concat(pub).drop_duplicates("id", keep="last")
RB = pd.read_parquet(f"{SP}/mna/out/arm3_oos_contrib.parquet", columns=["id", "day", "pred2", "pred3"]); RB["id"] = RB.id.astype(str)
RB = RB.drop_duplicates("id", keep="last")
PRED = {"sum_published": PUB.rename(columns={"pred": "p"})[["id", "day", "p"]],
        "sum_arm2_rebuild": RB.rename(columns={"pred2": "p"})[["id", "day", "p"]],
        "sum_arm3_rebuild": RB.rename(columns={"pred3": "p"})[["id", "day", "p"]]}

def score(order, tr, known):
    return {f"top{k}": len(set(order[:k]) & tr[k]) for k in K} | {f"ceiling_top{k}": len(tr[k] & known) for k in K}

def ex_ante(line, s, call_day, tr):
    """Call = 00:05 PT of call_day: launches of days s..call_day ranked by their own 00:05 prediction."""
    P = PRED[line]; days = [d.strftime("%Y-%m-%d") for d in pd.date_range(s, call_day)]
    have = sorted(set(P.day) & set(days)); miss = [d for d in days if d not in have]
    g = P[P.day.isin(days)].sort_values(["p", "id"], ascending=[False, True])
    return {"line": line, "call": f"{call_day:%Y-%m-%d} 00:05 PT", "days_missing_pred": miss, "n": int(len(g)), **score(g.id.tolist(), tr, set(g.id))}

def period_days(per, start):
    s = pd.Timestamp(start); e = s + pd.Timedelta(days=6) if per == "week" else s + pd.offsets.MonthEnd(0); return s, e

out = {"written_at": pd.Timestamp.now(tz="UTC").isoformat(), "periods": {}}
CLOSE = lambda e: (e + pd.Timedelta(days=1)).tz_localize(PT).tz_convert("UTC")

# ---- live periods
import period_parts as PP
from pipeline import warehouse as WH
WH.sync()
for per, start in (("week", "2026-11-09"), ("week", "2026-11-02"), ("month", "2026-10-01")):
    tr, meta = truth(per, start); s, e = period_days(per, start); close = CLOSE(e)
    R = {"period": [f"{s:%Y-%m-%d}", f"{e:%Y-%m-%d}"], "close_utc": close.isoformat(),
         "truth": {k: v for k, v in (meta or {}).items() if k != "ranks"}, "rows": []}
    if tr is None: R["status"] = "no truth"; out["periods"][f"{per}:{start}"] = R; continue
    calls = list(pd.date_range(s + pd.Timedelta(days=1), e)) if per == "week" else [s + pd.Timedelta(days=x) for x in (7, 14, 21, 28, 30)]
    for c in calls:
        for line in PRED: R["rows"].append(ex_ante(line, s, c, tr))
        # board at call c 00:05: votes through c-1 (+ entrants of c); live file for D = c-1 if present, else replay votes-only
        D = (c - pd.Timedelta(days=1)).strftime("%Y-%m-%d"); fn = f"{W}/{D}_{'weekly' if per == 'week' else 'monthly'}.json"
        if os.path.exists(fn):
            j = json.load(open(fn)); lines = {}
            if j.get("launches"): lines["board_" + j.get("board_line", "votes_only")] = [r["id"] for r in j["launches"]]
            if j.get("shadow_votes_only"): lines["board_votes_only"] = [r["id"] for r in j["shadow_votes_only"]]
            for ln, order in lines.items():
                R["rows"].append({"line": ln, "flag": "live", "call": f"{c:%Y-%m-%d} ~01:20 PT", "written_at": j.get("written_at"), "n": len(order), **score(order, tr, set(order))})
        else:
            run = pd.Timestamp(D, tz="UTC") + pd.Timedelta(days=1, hours=9, minutes=20)
            order, upd = PP.board(per, D, run)
            if order and not (per == "month" and pd.Timestamp(D).day < 10):
                R["rows"].append({"line": "board_votes_only", "flag": "replay", "call": f"{c:%Y-%m-%d} ~01:20 PT", "board_read": str(upd),
                                  "days_missing": PP.missing_days(per, D, run), "n": len(order), **score(order, tr, set(order))})
            else:
                R["rows"].append({"line": "board_votes_only", "flag": "replay", "call": f"{c:%Y-%m-%d}", "status": "no board (no held read before the call)"})
    if per == "week":   # the other writer's weekly_live files for this week
        for f in sorted(glob.glob(f"{W}/weekly_live/{start}_*.json")):
            j = json.load(open(f)); wa = pd.Timestamp(j["written_at"]); order = [r["id"] for r in sorted(j.get("forecast", []), key=lambda r: r["pred_rank"])]
            row = {"line": f"weekly_live:{j.get('point')}", "flag": "live", "day": j.get("day"), "written_at": j["written_at"], "n": len(order)}
            if wa >= close: row["status"] = "written after the close: not a forecast"
            else: row.update(score(order, tr, set(order)))
            R["rows"].append(row)
    out["periods"][f"{per}:{start}"] = R

# ---- backtest of the ex-ante sums (rebuild lines; Apr-Oct, full coverage), headline call = last day 00:05 and mid-period calls
def bt(per):
    keys = sorted(k for k, v in (TW if per == "week" else TM).items() if v.get("status") == "ok" and "2026-04-01" <= k and period_days(per, k)[1] <= pd.Timestamp("2026-10-31"))
    rows = []
    for k in keys:
        tr, _ = truth(per, k); s, e = period_days(per, k)
        for frac, c in (("last day", e), ("mid", s + pd.Timedelta(days=3 if per == "week" else 14))):
            for line in ("sum_arm2_rebuild", "sum_arm3_rebuild"):
                r = ex_ante(line, s, c, tr)
                if r["days_missing_pred"]: continue
                rows.append({**r, "period": k, "call": frac})
    df = pd.DataFrame(rows); res = {"periods": int(df.period.nunique()) if len(df) else 0}
    for (call, line), g in df.groupby(["call", "line"]):
        g = g.set_index("period"); rr = {}
        for kk in K:
            v = g[f"top{kk}"].values / kk * 100; bs = [rng.choice(v, len(v)).mean() for _ in range(2000)]
            rr[f"top{kk}"] = [round(v.mean(), 1), round(np.percentile(bs, 2.5), 1), round(np.percentile(bs, 97.5), 1)]
        res[f"{call} | {line}"] = rr
    for call in ("last day", "mid"):   # paired arm3 - arm2
        a = df[(df.call == call) & (df.line == "sum_arm3_rebuild")].set_index("period"); b = df[(df.call == call) & (df.line == "sum_arm2_rebuild")].set_index("period")
        a, b = a.align(b, join="inner", axis=0); rr = {}
        for kk in K:
            d = (a[f"top{kk}"] - b[f"top{kk}"]).values / kk * 100; bs = [rng.choice(d, len(d)).mean() for _ in range(2000)]
            rr[f"top{kk}"] = [round(d.mean(), 1), round(np.percentile(bs, 2.5), 1), round(np.percentile(bs, 97.5), 1)]
        res[f"{call} | arm3 minus arm2 (paired)"] = rr
    return res
out["backtest_ex_ante"] = {"week": bt("week"), "month": bt("month"),
                           "note": "hits / k x 100, mean over periods, period-bootstrap 95%; rebuild predictions are month-forward OOS, inputs dated before 00:05 of each launch day"}
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=str)
for k, R in out["periods"].items():
    print(k, R.get("truth", {}).get("source_part"))
    for r in R["rows"]:
        print("  ", r.get("line"), r.get("flag", ""), r.get("call", r.get("day")), r.get("status", ""), [r.get(f"top{x}") for x in K], [r.get(f"ceiling_top{x}") for x in K], r.get("days_missing_pred", ""), r.get("n"))
print(json.dumps(out["backtest_ex_ante"], indent=0))
