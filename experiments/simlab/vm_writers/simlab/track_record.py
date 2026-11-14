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
# TRUTH RULE (orchestrator 20:11Z Nov 14, after E5's independent recomputation): the first warehouse launches part written after the day's
# close (the initial snapshot counts as 2026-10-28T00:00Z), its daily_rank; a day counts when >= 10 launches are ranked; hits = our top k
# that finished with daily_rank <= k. Replaces the build-time dailyRank in a2x/X.parquet and the "first k ranked present" definition.
import period_parts as PP
_FP = {}
def first_part_truth(d):
    if d not in _FP:
        _FP[d] = None
        for ts, f in PP.parts():
            if ts < PP.close_utc(d): continue
            g = pd.read_parquet(f, columns=["id", "day", "daily_rank"]); g = g[g.day.astype(str).str[:10] == d]
            if len(g): _FP[d] = {str(i): float(r) for i, r in zip(g.id, g.daily_rank) if pd.notna(r)}; break
    return _FP[d]
def hits_k(order, T): return [int(len(set(order[:k]) & {i for i, r in T.items() if r <= k})) for k in (3, 5, 10)]
RESTATED = "restated Nov 14: truth from the first read after close (rank <= k); was {was}"
def backtest_rows(df, col, flag, line):
    for d, g in df.groupby("day"):
        T = first_part_truth(d) or {}; o = g.sort_values([col, "id"], ascending=[False, True]).id.astype(str).tolist(); nr = len(T)
        h = hits_k(o, T) if T else [None] * 3
        rows.append({"day": d, "prediction": "00:05 PT", "flag": flag, "line": line, "status": "scored" if nr >= 10 else "excluded: fewer than 10 ranked",
                     "n_launches": len(g), "n_ranked": nr, "hits_top3": h[0], "hits_top5": h[1], "hits_top10": h[2]})
X = pd.read_parquet(f"{SP}/a2x/X.parquet"); X["id"] = X.id.astype(str); X["day"] = X.day.astype(str).str[:10]
backtest_rows(X, "both", "backtest", "arm 2 walk-forward fold")
_CN = f"{SP}/a2x/history_retrain_decomp_preds_arm2.parquet"   # PH ops' month-forward preds; 'pure' = clean_nosite
if os.path.exists(_CN):
    Hc = pd.read_parquet(_CN); Hc["id"] = Hc.id.astype(str); Hc["day"] = Hc.day.astype(str).str[:10]
    backtest_rows(Hc, "pure", "backtest (clean_nosite, fallback model)", "clean_nosite (published only when arm 2 is missing)")
# 03:45 replay = the line that will be published (bundle 12a hybrid_vm, PH ops' per-day replay hits, read rule agreed with E5, LODO
# weights); E5's re-implementation of the earlier hybrid (78.2 top 10) is no longer used here (orchestrator / PH ops, Nov 14).
# 03:45 replay rows (orchestrator 20:31Z Nov 14): scored here from per-day ORDERS (assets a2x/replay_orders_345.json: PH ops' leave-one-day-out
# hybrid orders + the recorder's hidden order, every launch in the 03:00 read kept as in the live file), with the live scoreboard's rule.
_RO = f"{SP}/a2x/replay_orders_345.json"
RO = json.load(open(_RO)) if os.path.exists(_RO) else {"days": {}}
for d, v in sorted(RO["days"].items()):
    T = first_part_truth(d) or {}; nr = len(T)
    for flag, key, line in (("replay", "hybrid", "hybrid_vm (bundle 12a), PH ops leave-one-day-out orders, live 00:05 prior"),
                            ("replay with fixed 00:05 inputs", "hybrid_fixed", "hybrid_vm with the fixed-prior weights (bundle 12a.3), PH ops leave-one-day-out orders"),
                            ("replay (hidden rank alone)", "hidden", "Product Hunt's hidden order at the 03:00 read")):
        if key not in v: continue
        h = hits_k(v[key], T) if T else [None] * 3
        rows.append({"day": d, "prediction": "03:45 PT", "flag": flag, "line": line, "status": "scored" if nr >= 10 else "excluded: fewer than 10 ranked",
                     "n_ranked": nr, "n_launches": len(v[key]), "hits_top3": h[0], "hits_top5": h[1], "hits_top10": h[2]})
today = pd.Timestamp.now(tz="America/Los_Angeles").strftime("%Y-%m-%d")
for d in [x for x in pd.date_range("2026-11-14", today).strftime("%Y-%m-%d") if x < today]:   # closed PT days only
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
        T = first_part_truth(d)
        if T is None: rows.append({**base, "status": "pending final ranks"}); continue
        if len(T) < 10: rows.append({**base, "status": "excluded: fewer than 10 ranked", "n_ranked": len(T)}); continue
        F["id"] = F.id.astype(str); o = F.dropna(subset=[col]).sort_values(col).id.tolist(); h = hits_k(o, T)
        rows.append({**base, "status": "scored", "n_launches": len(T), "hits_top3": h[0], "hits_top5": h[1], "hits_top10": h[2]})
def ci(v):
    v = np.asarray(v, float); bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(4000)]
    return [round(float(v.mean()), 1), round(float(np.percentile(bs, 2.5)), 1), round(float(np.percentile(bs, 97.5)), 1), len(v)]
DAY_RULE = "a day counts only when >= 10 of its launches have an official daily rank (same rule for backtest, replay and live)"
S = pd.DataFrame(rows); summ = {}
for (pred, flag), g in S[S.status == "scored"].groupby(["prediction", "flag"]):
    g = g.sort_values("day"); o = {}
    for nm, gg in (("last 7 days", g.tail(7)), ("last 30 days", g.tail(30)), ("all days", g)):
        o[nm] = {f"top{k} hits %": ci(gg[f"hits_top{k}"] / k * 100) for k in (3, 5, 10)}
    o["share of days with 0/1/2/3 of the top 3 right"] = {str(k): round(float((g.hits_top3 == k).mean()), 3) for k in range(4)}
    o["first/last day"] = [g.day.iloc[0], g.day.iloc[-1]]; o["n_days"] = int(len(g)); o["day rule"] = DAY_RULE; summ[f"{pred} | {flag}"] = o
    if flag == "live" and "model" in g:   # arm 3 pre-publish audit: never let one live line hide a model change (arm 2 days vs arm 3 days)
        mg = g.assign(m=g.model.fillna("unknown").astype(str) + g.fallback_used.map(lambda x: f" (fallback: {x})" if isinstance(x, str) and x else ""))
        o["models"] = mg.m.value_counts().to_dict()
        if mg.m.nunique() > 1:
            o["WARNING"] = "this live line mixes days from more than one published model; show the per-model lines below, not the pooled one"
            o["by model"] = {m: {"n_days": int(len(gm)), "first/last day": [gm.day.iloc[0], gm.day.iloc[-1]],
                                 **{f"top{k} hits %": ci(gm[f"hits_top{k}"] / k * 100) for k in (3, 5, 10)}} for m, gm in mg.groupby("m")}
for (pred, flag), g in S[S.status.isin(["scored", "excluded: fewer than 10 ranked"]) & S.hits_top3.notna()].groupby(["prediction", "flag"]):
    if (g.status != "scored").any() and f"{pred} | {flag}" in summ:   # labelled extra, never the headline: every day incl. short lists
        summ[f"{pred} | {flag}"]["extra: all days incl. fewer than 10 ranked (not comparable to live)"] = {
            "n_days": int(len(g)), **{f"top{k} hits %": ci(g[f"hits_top{k}"] / k * 100) for k in (3, 5, 10)}}
RO_NOTE = ("orders keep every launch in the 03:00 read (unranked launches stay in the day inputs and the weights are refit, as the live 03:45 "
           "writer does); an unranked pick counts as a miss, as on the live scoreboard (settled Nov 14)")
for k_, extra in (("03:45 PT | replay", ""), ("03:45 PT | replay (hidden rank alone)", ""),
                  ("03:45 PT | replay with fixed 00:05 inputs", "; not live until the today-rows fix and bundle 12a.3 are deployed")):
    if k_ in summ: summ[k_]["note"] = RO_NOTE + extra
# (orchestrator 15:52Z Nov 14, explanation audit item 1) the line published Oct 29 - Nov 13 was NOT arm 2 / clean_nosite: Oct 29 - Nov 12 the
# old FULL launch model (all live inputs incl. named-maker inputs and llm_site; forecast.py before af6c25c2), Nov 13 clean_nosite
# (scoreboard model_switch clean_from 2026-11-13). Figure from results/web/scoreboard.json summary (point 0005, method published, live).
summ["00:05 PT | live, previous published model"] = {"line": "old full launch model (Oct 29 - Nov 12) then clean_nosite (Nov 13)", "flag": "live", "n_days": 11,
    "first/last day": ["2026-10-29", "2026-11-13"], "all days": {"top3 hits %": [51.5, 39.4, 63.6, 11], "top5 hits %": [60.0, None, None, 11], "top10 hits %": [73.6, None, None, 11]},
    "source": "results/web/scoreboard.json summary (0005 / published / live)", "day rule": DAY_RULE}
for k_, was in (("00:05 PT | backtest", "58.1 / 65.2 / 76.9 on 183 days"), ("00:05 PT | backtest (clean_nosite, fallback model)", "54.5 / 64.7 / 76.0 on 183 days")):
    if k_ in summ: summ[k_]["note"] = RESTATED.format(was=was)
out = {"version": "track_record_v1", "written_at": pd.Timestamp.now(tz="UTC").isoformat(),
       "READ_ME": "backtest = model re-run on past days it was not trained on (00:05, Apr-Oct); replay = the 03:45 rule re-run on recorded "
                  "pre-reveal reads (Nov 2-13); live = what the site actually published, scored against the official daily rank. Never pool "
                  "or average across flags; show each with its own label and interval. Intervals: 95% day bootstrap. Hits = how many of our "
                  "top k were in the real top k.",
       "summary": summ, "days": rows}
p = os.path.join(SP, "track_record_v1.json"); json.dump(out, open(p, "w"), indent=1, default=float)
subprocess.run(["gsutil", "-q", "cp", p, f"{B}/tmp/e5/website/track_record_v1.json"], check=True)
print(json.dumps(summ, default=float)[:3000]); print("statuses", S.groupby(["prediction", "flag", "status"]).size().to_dict())
