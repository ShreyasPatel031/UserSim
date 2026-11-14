"""Topic momentum at 00:05, as-of only (orchestrator 13:09Z Nov 14). Builds per-launch topic features from the day files (2025 + 2026;
~/w/h25/data/days = 2026 store + 2025 history lists) for the arm-2 JOINT harness (history_retrain.py JOINT=1 JOINT_KEEP_2025=1).
Not run before: lm_breakout.py C1 (Nov 11) used a d-8..d-2 window on the honest LM; this is 30/90-day windows, share trend, line-up share
and topic x weekday on arm 2.

Labels (votes, ranks) for a launch on day d come only from days <= d-2 (closed AND settled: the stored votes are later reads, so d-1's
final votes would leak post-close votes). Line-up composition (no labels) uses days <= d-1 and, for tm_day_share, day d's own line-up
(known at 00:05).
Per topic t, at day d:
  rel  = launch log1p(votes) minus its day mean;  top10 = dailyRank <= 10
  m30/m90   mean rel over t's launches dated d-31..d-2 / d-91..d-2, shrunk to 0 by n / (n + 10)
  t30/t90   top-10 rate over the same windows, shrunk to the global rate by n / (n + 10)
  trend     log((share of line-ups with t, d-30..d-1 + 1e-3) / (share, d-120..d-31 + 1e-3))   (rising > 0)
  wd        top-10 rate of t on the same weekday, d-91..d-2, shrunk to the global rate by n / (n + 5)
  day_share share of day d's line-up carrying t
Per launch: max and mean over its topics (tm_<x>_max, tm_<x>_mean); tm_n_topics. Launch ids and numbers only.
usage (VM): python3 topic_momentum.py <days dir> <out.parquet>"""
import glob, json, os, sys
import numpy as np, pandas as pd

R = []
for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.json"))):
    d = os.path.basename(f)[:-5]
    for p in json.load(open(f)):
        tp = p.get("topics") or {}
        ts = [e["node"]["name"] for e in tp.get("edges", [])] if isinstance(tp, dict) else [t if isinstance(t, str) else t.get("name") for t in tp]
        R.append({"id": str(p["id"]), "day": d, "votes": p.get("votesCount"), "rank": p.get("dailyRank"), "topics": ts})
L = pd.DataFrame(R).drop_duplicates("id", keep="last")
L["votes"] = pd.to_numeric(L.votes, errors="coerce"); L["rank"] = pd.to_numeric(L["rank"], errors="coerce")
L["lv"] = np.log1p(L.votes); L["rel"] = L.lv - L.groupby("day").lv.transform("mean"); L["top10"] = (L["rank"] <= 10).astype(float)
L["dt"] = pd.to_datetime(L.day); L["wd"] = L.dt.dt.dayofweek
E = L.explode("topics").dropna(subset=["topics"])
days = sorted(L.day.unique()); G10 = float(L.top10.mean())
# per-day per-topic aggregates, then cumulative sums for O(1) window queries
agg = E.groupby(["day", "topics"]).agg(n=("id", "size"), s_rel=("rel", "sum"), s_t10=("top10", "sum")).reset_index()
nday = L.groupby("day").size()
piv = {c: agg.pivot(index="day", columns="topics", values=c).reindex(days).fillna(0.0) for c in ("n", "s_rel", "s_t10")}
cum = {c: v.cumsum() for c, v in piv.items()}
cum_lineups = nday.reindex(days).cumsum()
di = {d: i for i, d in enumerate(days)}
dts = pd.to_datetime(pd.Series(days))


def win(c, d, a, b):   # sum over days in [d-a, d-b] (calendar), per topic
    lo = (pd.Timestamp(d) - pd.Timedelta(days=a)).strftime("%Y-%m-%d"); hi = (pd.Timestamp(d) - pd.Timedelta(days=b)).strftime("%Y-%m-%d")
    i_hi = np.searchsorted(days, hi, side="right") - 1; i_lo = np.searchsorted(days, lo, side="left") - 1
    if i_hi < 0 or i_hi <= i_lo:
        return pd.Series(0.0, index=cum[c].columns) if c in cum else 0.0
    src = cum[c] if c in cum else cum_lineups
    return src.iloc[i_hi] - (src.iloc[i_lo] if i_lo >= 0 else 0.0)


# weekday tables: same idea per weekday
wd_piv = {w: {c: agg[agg.day.map(lambda x: pd.Timestamp(x).dayofweek) == w].pivot(index="day", columns="topics", values=c).reindex(days).fillna(0.0).cumsum()
              for c in ("n", "s_t10")} for w in range(7)}
OUT = []
for d, g in L.groupby("day"):
    n30, r30, t30 = win("n", d, 31, 2), win("s_rel", d, 31, 2), win("s_t10", d, 31, 2)
    n90, r90, t90 = win("n", d, 91, 2), win("s_rel", d, 91, 2), win("s_t10", d, 91, 2)
    sh_a = win("n", d, 30, 1) / max(float(win("lineups", d, 30, 1)), 1.0)
    sh_b = win("n", d, 120, 31) / max(float(win("lineups", d, 120, 31)), 1.0)
    trend = np.log((sh_a + 1e-3) / (sh_b + 1e-3))
    w = pd.Timestamp(d).dayofweek; cw = wd_piv[w]
    hi = np.searchsorted(days, (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d"), side="right") - 1
    lo = np.searchsorted(days, (pd.Timestamp(d) - pd.Timedelta(days=91)).strftime("%Y-%m-%d"), side="left") - 1
    if hi >= 0 and hi > lo:
        nw = cw["n"].iloc[hi] - (cw["n"].iloc[lo] if lo >= 0 else 0.0); tw = cw["s_t10"].iloc[hi] - (cw["s_t10"].iloc[lo] if lo >= 0 else 0.0)
    else:
        nw = pd.Series(0.0, index=cum["n"].columns); tw = nw
    ex = g.explode("topics"); dsh = ex.topics.value_counts() / len(g)
    feats = {
        "m30": (r30 / n30.replace(0, np.nan)).fillna(0) * n30 / (n30 + 10),
        "m90": (r90 / n90.replace(0, np.nan)).fillna(0) * n90 / (n90 + 10),
        "t30": (t30 + 10 * G10) / (n30 + 10), "t90": (t90 + 10 * G10) / (n90 + 10),
        "trend": trend, "wd": (tw + 5 * G10) / (nw + 5), "day_share": dsh}
    for _, r in g.iterrows():
        ts = [t for t in r.topics if t]
        row = {"id": r.id, "tm_n_topics": float(len(ts))}
        for k, s in feats.items():
            v = [float(s.get(t, 0.0 if k not in ("t30", "t90", "wd") else G10)) for t in ts]
            row[f"tm_{k}_max"] = max(v) if v else np.nan; row[f"tm_{k}_mean"] = float(np.mean(v)) if v else np.nan
        OUT.append(row)
O = pd.DataFrame(OUT); O.to_parquet(sys.argv[2])
print(json.dumps({"launches": len(O), "days": len(days), "first_day": days[0], "last_day": days[-1], "cols": [c for c in O.columns if c != "id"],
                  "filled": round(float(O.tm_m90_max.notna().mean()), 3)}))
