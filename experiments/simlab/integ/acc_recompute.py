"""Independent recomputation of every published accuracy number (orchestrator 20:06Z Nov 14). Fresh code: imports no writer.
Truth for day d: the FIRST warehouse `launches` part written after d's close (d+1 00:00 PT) that holds rows of d (the initial snapshot counts
as written 2026-10-28T00:00Z), its daily_rank; a day counts only when >= 10 of its launches have a rank. top-k hits % = |pred top k ∩
{launches with daily_rank <= k}| / k x 100, mean over days. Rows compared: track_record_v1.json summary (5), scoreboard.json non-shadow
summary rows (day lists as the scoreboard's own per-day rows state), period_track_record.json entries.
    python acc_recompute.py <acc dir> <recorder dir> <out json>"""
import glob, json, os, re, sys
import numpy as np, pandas as pd
A, REC, OUT = sys.argv[1:4]; PT = "America/Los_Angeles"; rng = np.random.default_rng(0)
PARTS = []
for f in glob.glob(f"{A}/parts/*.parquet"):
    m = re.match(r"(\d{8}T\d{6})", os.path.basename(f)); PARTS.append((pd.Timestamp(m.group(1), tz="UTC") if m else pd.Timestamp("2026-10-28T00:00Z"), f))
PARTS.sort(); _cache = {}
def part(f):
    if f not in _cache:
        x = pd.read_parquet(f, columns=["id", "day", "daily_rank", "weekly_rank", "monthly_rank", "votes"]); x["id"] = x.id.astype(str); x["day"] = x.day.astype(str).str[:10]; _cache[f] = x
    return _cache[f]
_truth = {}
def truth(d):
    if d not in _truth:
        close = pd.Timestamp(d, tz=PT) + pd.Timedelta(days=1); _truth[d] = (None, None)
        for ts, f in PARTS:
            if ts < close.tz_convert("UTC"): continue
            g = part(f); g = g[g.day == d]
            if len(g): _truth[d] = (dict(zip(g.id, g.daily_rank)), f"{os.path.basename(f)}"); break
    return _truth[d]
def ranked(d):
    T, _ = truth(d); return {i: int(r) for i, r in (T or {}).items() if pd.notna(r)}
def hits(order, d):
    R = ranked(d); return [100 * len(set(order[:k]) & {i for i, r in R.items() if r <= k}) / k for k in (3, 5, 10)]
def mean_ci(v):
    v = np.asarray(v, float); b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)] if len(v) else [np.nan]
    return [round(float(v.mean()), 1) if len(v) else None, round(float(np.percentile(b, 2.5)), 1), round(float(np.percentile(b, 97.5)), 1), len(v)]
def score(orders, days=None):
    """orders: {day: [ids best first]}. days=None -> every day with >= 10 ranked."""
    use = sorted(d for d in orders if (days is None and len(ranked(d)) >= 10) or (days is not None and d in days))
    H = np.array([hits(orders[d], d) for d in use]) if use else np.zeros((0, 3))
    return {"top3": mean_ci(H[:, 0]) if len(use) else None, "top5": mean_ci(H[:, 1])[0] if len(use) else None, "top10": mean_ci(H[:, 2])[0] if len(use) else None,
            "n_days": len(use), "days": [use[0], use[-1]] if use else None, "days_lt10_ranked_included": [d for d in use if len(ranked(d)) < 10]}
def cmp(pub, rec, tol=0.05):
    """pub = [top3, top5, top10, n_days]"""
    if rec is None or rec.get("top3") is None: return "not recomputable"
    got = [rec["top3"][0], rec["top5"], rec["top10"], rec["n_days"]]
    d = [None if p is None else round(g - p, 1) for g, p in zip(got, pub)]
    return "match" if all(x is None or abs(x) <= tol for x in d[:3]) and (pub[3] is None or d[3] == 0) else f"differs {d} (top3/5/10 points, days)"
OUTR = {"truth rule": __doc__.split("Truth")[1].split("Rows")[0].strip(), "track_record_v1": {}, "scoreboard": {}, "period": {}}
by_day = lambda df, col, asc=False: {d: g.sort_values([col, "id"], ascending=[asc, True]).id.astype(str).tolist() for d, g in df.groupby("day")}
# ---------------- track_record_v1 ----------------
TR = json.load(open(f"{A}/track_record_v1.json")); S = TR["summary"]
pubv = lambda k: [S[k]["all days"]["top3 hits %"][0], S[k]["all days"]["top5 hits %"][0], S[k]["all days"]["top10 hits %"][0], S[k]["all days"]["top3 hits %"][3]]
X = pd.read_parquet(f"{A}/../a2x/X.parquet"); X["id"] = X.id.astype(str); X["day"] = X.day.astype(str).str[:10]
H = pd.read_parquet(f"{A}/../history_retrain_decomp_preds_arm2.parquet"); H["id"] = H.id.astype(str); H["day"] = H.day.astype(str).str[:10]
def row(name, pub, rec, why=""):
    OUTR["track_record_v1"][name] = {"published": pub, "recomputed": rec, "verdict": cmp(pub, rec), "note": why}
row("00:05 PT | backtest", pubv("00:05 PT | backtest"), score(by_day(X, "both")), "preds: assets a2x/X.parquet 'both' (arm 2 walk-forward)")
OUTR["track_record_v1"]["00:05 PT | backtest"]["X dailyRank (build-time truth) instead"] = score({d: o for d, o in by_day(X, "both").items()}, None) if False else None
row("00:05 PT | backtest (clean_nosite, fallback model)", pubv("00:05 PT | backtest (clean_nosite, fallback model)"), score(by_day(H, "pure")), "preds: history_retrain_decomp_preds_arm2.parquet 'pure'")
# live previous published model: results/web/forecast_0005/<d>.json predicted_rank, days Oct 29 - Nov 13 written live
FC = {}
for f in glob.glob(f"{A}/fc0005/*.json"):
    j = json.load(open(f)); d = os.path.basename(f)[:10]; fc = j.get("forecast") if isinstance(j, dict) else j
    if fc: FC[d] = [str(r["id"]) for r in sorted(fc, key=lambda r: r.get("predicted_rank") or 999)]
SB = json.load(open(f"{A}/scoreboard.json"))
live_days = sorted(r["day"] for r in SB["rows"] if r["point"] == "0005" and r["method"] == "published" and r["source"] == "live")
row("00:05 PT | live, previous published model", pubv("00:05 PT | live, previous published model"), score(FC, set(live_days)),
    f"preds: results/web/forecast_0005/<d>.json; days = the scoreboard's live rows {live_days[0]}..{live_days[-1]}")
OUTR["track_record_v1"]["00:05 PT | live, previous published model"]["same files, every day >= 10 ranked Oct 29+"] = score({d: o for d, o in FC.items() if d >= "2026-10-29" and d < "2026-11-14"})
# 03:45 replay rows: orders are not stored; recompute the hidden-order line from the recorder, and the hybrid line from PH ops' per-day hits
HV = json.load(open(f"{A}/hybrid_vmonly_days.json"))["days"]
hv = np.array([[100 * x["hits_top3"] / 3, 100 * x["hits_top5"] / 5, 100 * x["hits_top10"] / 10] for x in HV])
rec = {"top3": [round(float(hv[:, 0].mean()), 1)], "top5": round(float(hv[:, 1].mean()), 1), "top10": round(float(hv[:, 2].mean()), 1), "n_days": len(HV), "days": [HV[0]["day"], HV[-1]["day"]]}
row("03:45 PT | replay", pubv("03:45 PT | replay"), rec, "orders not stored: mean of PH ops' per-day hits (tmp/ph_ops/hybrid_vmonly_days.json) only; truth not re-read")
def hidden(d, hm="03:45", tol_min=65):
    p = f"{REC}/{d}.jsonl"
    if not os.path.exists(p): return None
    V = pd.DataFrame([json.loads(l) for l in open(p)]); V["a"] = pd.to_datetime(V["at"], utc=True); T = pd.Timestamp(f"{d} {hm}", tz=PT).tz_convert("UTC")
    s = V[(V.a <= T + pd.Timedelta(seconds=90)) & (V.a >= T - pd.Timedelta(minutes=tol_min)) & (V.a >= pd.Timestamp(d, tz=PT).tz_convert("UTC") - pd.Timedelta(minutes=5))].dropna(subset=["rank_now"])
    if s.empty: return None
    s = s.sort_values("a").groupby(s.launch_id.astype(str)).last(); return list(s.sort_values(["rank_now"]).index.astype(str))
HO = {d: o for d in [x["day"] for x in HV] + ["2026-11-13"] if (o := hidden(d))}
row("03:45 PT | replay (hidden rank alone)", pubv("03:45 PT | replay (hidden rank alone)"), score(HO, set(HO)), "recorder rank_now, latest read <= 03:45 PT within 65 min (= the 03:00 read), Nov 2-13")
# ---------------- scoreboard (non-shadow) ----------------
FIELD = {"best": "pred_rank_best", "api_rank": "pred_rank_api", "blend": "pred_rank_blend", "comment_ridge": "pred_rank", "hybrid": "pred_rank_hybrid", "raw_votes": "pred_rank"}
def early_order(d, point, method):
    p = f"{A}/early/{d}_{point}.json"
    if not os.path.exists(p): return None
    f = (json.load(open(p)) or {}).get("forecast") or []; fld = FIELD.get(method, f"pred_rank_{method}")
    rows = [(str(r["id"]), r[fld]) for r in f if isinstance(r.get(fld), (int, float))]
    return [i for i, _ in sorted(rows, key=lambda t: (t[1], t[0]))] if rows else None
SBR = pd.DataFrame(SB["rows"])
for r in SB["summary"]:
    if r.get("source") == "shadow": continue
    key = f"{r['point']} | {r['method']} | {r['source']}"; sub = SBR[(SBR.point == r["point"]) & (SBR.method == r["method"]) & (SBR.source == r["source"])]
    days = set(sub.day); orders = {}
    for d in days:
        o = FC.get(d) if r["point"] == "0005" else early_order(d, r["point"], r["method"])
        if o: orders[d] = o
    pub = [r.get("mean_top3"), r.get("mean_top5"), r.get("mean_top10"), r.get("days")]
    rec = score(orders, days) if orders else None
    v = cmp(pub, rec) if len(orders) == len(days) else (f"partial: {len(orders)}/{len(days)} days have stored orders; " + cmp([*pub[:3], len(orders)], rec) if orders else "not recomputable (no stored order for this method)")
    lt10 = [d for d in days if len(ranked(d)) < 10]
    OUTR["scoreboard"][key] = {"published": pub, "recomputed": rec and [rec["top3"][0], rec["top5"], rec["top10"], rec["n_days"]], "verdict": v, "days with < 10 ranked in its day list": sorted(lt10)}
# ---------------- period_track_record ----------------
P = json.load(open(f"{A}/period_track_record.json"))
for e in P["entries"]:
    k = f"{e.get('board')} {e.get('period_start')} | {e.get('flag')} | {e.get('line')}"
    OUTR["period"][k] = {"published hits": e.get("hits top3/5/10"), "status": e.get("status"), "truth_read_pt": e.get("truth_read_pt"), "board_read": e.get("board_read"),
                         "verdict": "not recomputed here (board orders live in the period files; see note)"}
json.dump(OUTR, open(OUT, "w"), indent=1, default=str)
for sec in ("track_record_v1", "scoreboard"):
    for k, v in OUTR[sec].items(): print(sec, "|", k, "|", v["published"], "->", v["recomputed"] if sec == "scoreboard" else (v["recomputed"] and [v["recomputed"]["top3"][0], v["recomputed"]["top5"], v["recomputed"]["top10"], v["recomputed"]["n_days"]]), "|", v["verdict"])
