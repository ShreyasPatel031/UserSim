"""Track record for the website's two published predictions (orchestrator 01:02Z Nov 14). Bucket only: tmp/e5/website/track_record_v1.json.
Counts, dates and launch ids only. Per PT day and prediction: hits in the top 3 / 5 / 10 (picks vs official daily_rank), the line used, and a
flag. NEVER pooled across flags:
  "backtest"  00:05: PH ops' arm-2 walk-forward fold (month-forward, 5 seeds), Apr 1 - Oct 31 (214 days), from the arm2_explain dump
  "replay"    03:45: the hybrid (plain hidden top 5 + hr_clean slots 6+, weights leave-one-day-out) re-scored by E5 from raw recorder files,
              Nov 2-12 (11 days; prereveal_345.py)
  "live"      from Nov 14: 00:05 = results/web/forecast_0005/<day>.json predicted_rank; 03:45 = results/early_forecast/<day>_P345.json
              pred_rank_hybrid; label = warehouse daily_rank once final. A missing prediction file -> status "not published" (day kept).
Summary per prediction and flag: last 7 / last 30 / all days mean hits % with day-bootstrap 95% intervals, and the share of days with
0 / 1 / 2 / 3 of the top 3 right.
    python track_record.py <scratchpad>      (rebuilds the whole file; run nightly from forward_nightly.sh)
"""
import json, os, subprocess, sys
import numpy as np, pandas as pd
SP = sys.argv[1]; HERE = os.path.dirname(os.path.abspath(__file__)); B = "gs://usersim-bakeoff-347838016394/usersim_sim"; rng = np.random.default_rng(0)
sys.path.insert(0, os.path.dirname(HERE)); from pipeline import warehouse as W
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
L = W.table("launches", do_sync=True).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L = L[L.daily_rank.notna()]
RK = {d: dict(zip(g.id, g.daily_rank.astype(float))) for d, g in L.groupby("day")}
def hits(pred_order, d):
    t = sorted(RK[d], key=lambda i: RK[d][i]); return [int(len(set(pred_order[:k]) & set(t[:k]))) for k in (3, 5, 10)]
rows = []
X = pd.read_parquet(f"{SP}/a2x/X.parquet"); X["id"] = X.id.astype(str)
for d, g in X.groupby("day"):
    t = g.sort_values("dailyRank").id.tolist(); o = g.sort_values(["both", "id"], ascending=[False, True]).id.tolist()
    rows.append({"day": d, "prediction": "00:05 PT", "flag": "backtest", "line": "arm 2 walk-forward fold", "status": "scored", "n_launches": len(g),
                 "hits_top3": len(set(o[:3]) & set(t[:3])), "hits_top5": len(set(o[:5]) & set(t[:5])), "hits_top10": len(set(o[:10]) & set(t[:10]))})
R = json.load(open(os.path.join(HERE, "reports", "prereveal_345", "prereveal_345.json")))["per day (plain, hybrid) top3/5/10 hits %"]
for d, v in R.items():
    h = [int(round(x * k / 100)) for x, k in zip(v["hybrid"], (3, 5, 10))]
    rows.append({"day": d, "prediction": "03:45 PT", "flag": "replay", "line": "hybrid (hidden top 5 + hr_clean 6+), LODO", "status": "scored", "n_launches": v["n launches"],
                 "hits_top3": h[0], "hits_top5": h[1], "hits_top10": h[2]})
today = pd.Timestamp.now(tz="America/Los_Angeles").strftime("%Y-%m-%d")
for d in pd.date_range("2026-11-14", today, inclusive="left").strftime("%Y-%m-%d"):
    for pred, path, col0, newp in (("00:05 PT", f"{B}/results/web/forecast_0005/{d}.json", "predicted_rank", f"{B}/results/web/predictions/{d}_0005.json"),
                                  ("03:45 PT", f"{B}/results/early_forecast/{d}_P345.json", "pred_rank_hybrid", f"{B}/results/web/predictions/{d}_prereveal.json")):
        col = col0; raw, used = gcat(newp), newp   # bundle 12a paths (model name + fallback_used) when present, the old paths otherwise
        if not raw: raw, used = gcat(path), path
        base = {"day": d, "prediction": pred, "flag": "live", "line": "published file " + used.split("/results/")[1]}
        if not raw: rows.append({**base, "status": "not published"}); continue
        J = json.loads(raw); base.update({"model": J.get("model") or J.get("method"), "fallback_used": J.get("fallback_used")})
        if used == newp: F = pd.DataFrame(J.get("ranking") or []); col = "rank"   # bundle 12a: ranking [{rank, id, name(, score)}], rank 1 = top pick
        else: F = pd.DataFrame(J.get("forecast") or [])
        if F.empty or col not in F: rows.append({**base, "status": "not published"}); continue
        if d not in RK or len(RK[d]) < 10: rows.append({**base, "status": "pending final ranks"}); continue
        F["id"] = F.id.astype(str); o = F.dropna(subset=[col]).sort_values(col).id.tolist(); h = hits(o, d)
        rows.append({**base, "status": "scored", "n_launches": len(RK[d]), "hits_top3": h[0], "hits_top5": h[1], "hits_top10": h[2]})
def ci(v):
    v = np.asarray(v, float); bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(4000)]
    return [round(float(v.mean()), 1), round(float(np.percentile(bs, 2.5)), 1), round(float(np.percentile(bs, 97.5)), 1), len(v)]
S = pd.DataFrame(rows); summ = {}
for (pred, flag), g in S[S.status == "scored"].groupby(["prediction", "flag"]):
    g = g.sort_values("day"); o = {}
    for nm, gg in (("last 7 days", g.tail(7)), ("last 30 days", g.tail(30)), ("all days", g)):
        o[nm] = {f"top{k} hits %": ci(gg[f"hits_top{k}"] / k * 100) for k in (3, 5, 10)}
    o["share of days with 0/1/2/3 of the top 3 right"] = {str(k): round(float((g.hits_top3 == k).mean()), 3) for k in range(4)}
    o["first/last day"] = [g.day.iloc[0], g.day.iloc[-1]]; summ[f"{pred} | {flag}"] = o
out = {"version": "track_record_v1", "written_at": pd.Timestamp.now(tz="UTC").isoformat(),
       "READ_ME": "backtest = model re-run on past days it was not trained on (00:05, Apr-Oct); replay = the 03:45 rule re-run on recorded "
                  "pre-reveal reads (Nov 2-12); live = what the site actually published, scored against the official daily rank. Never pool "
                  "or average across flags; show each with its own label and interval. Intervals: 95% day bootstrap. Hits = how many of our "
                  "top k were in the real top k.",
       "summary": summ, "days": rows}
p = os.path.join(SP, "track_record_v1.json"); json.dump(out, open(p, "w"), indent=1, default=float)
subprocess.run(["gsutil", "-q", "cp", p, f"{B}/tmp/e5/website/track_record_v1.json"], check=True)
print(json.dumps(summ, default=float)[:3000]); print("statuses", S.groupby(["prediction", "flag", "status"]).size().to_dict())
