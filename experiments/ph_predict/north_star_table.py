"""ONE source for every published accuracy figure (orchestrator 20:51Z Nov 14): results/web/north_star_table.json (+ bucket copy).
Every row is computed here from stored per-day orders / predictions; nothing is typed in. Rule for every row (unless the row says otherwise):
truth = final daily rank <= k from the warehouse launches table, days with >= 10 ranked launches, unranked picks count as misses.
Rows: 00:05 backtests (arm 2, clean_nosite, arm 3) month-forward Apr-Oct 2026; 00:05 live rows by producing model (scoreboard_orders.json);
before-reveal hidden alone and the hybrid with the live and the fixed prior (12+ days, LODO, orders incl. unranked launches);
weekly board (b) with predicted entrants. Regenerated nightly (run after scoreboard.py). usage: python3 north_star_table.py"""
import json, os, subprocess, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
from pipeline import warehouse as W
R = lambda p: os.path.join(HERE, "results", p)
Rk = W.query("SELECT CAST(id AS VARCHAR) id, day, daily_rank FROM launches WHERE daily_rank IS NOT NULL", do_sync=False)
Rk["day"] = Rk.day.astype(str).str[:10]; TRUTH = {d: g.sort_values("daily_rank") for d, g in Rk.groupby("day")}
def hk(order, d):
    g = TRUTH.get(d)
    if g is None or len(g) < 10: return None
    return [len(set(map(str, order[:k])) & set(g.id[g.daily_rank <= k])) / k * 100 for k in (3, 5, 10)]
def row(point, model, method, H, days, src, rule="final daily rank <= k, >= 10 ranked, unranked picks = misses"):
    H = np.array([h for h in H if h is not None])
    return {"point": point, "model": model, "method": method, "top3": round(float(H[:, 0].mean()), 1) if len(H) else None,
            "top5": round(float(H[:, 1].mean()), 1) if len(H) else None, "top10": round(float(H[:, 2].mean()), 1) if len(H) else None,
            "n_days": int(len(H)), "first_day": min(days) if days else None, "last_day": max(days) if days else None, "rule": rule, "source": src}
rows = []
# 00:05 backtests
A = pd.read_parquet(R("history_retrain_decomp_preds_arm2.parquet")); A["id"] = A.id.astype(str)
for col, model in (("both", "arm2"), ("pure", "clean_nosite")):
    H, D = [], []
    for d, g in A.groupby("day"):
        h = hk(g.sort_values([col, "id"], ascending=[False, True]).id.tolist(), d)
        if h is not None: H.append(h); D.append(d)
    rows.append(row("0005", model, "backtest, month-forward Apr-Oct 2026, 5 seeds (as published)", H, D, "results/history_retrain_decomp_preds_arm2.parquet"))
if os.path.exists(R("arm3_vs_arm2_preds.parquet")):
    P = pd.read_parquet(R("arm3_vs_arm2_preds.parquet")); P["id"] = P.id.astype(str); P = P[P.year == "2026"]
    for col, model in (("arm3", "arm3"), ("arm2", "arm2 (20 seeds, arm-3 harness)")):
        H, D = [], []
        for d, g in P.groupby("day"):
            h = hk(g.sort_values([col, "id"], ascending=[False, True]).id.tolist(), d)
            if h is not None: H.append(h); D.append(d)
        rows.append(row("0005", model, "backtest, month-forward Apr-Oct 2026, 20 seeds, pre-registered harness", H, D, "results/arm3_vs_arm2_preds.parquet"))
# explanation model (why drivers): readable v2 stumps, column b of the backtest predictions (no th_n_pre: the th_n_pre variant's orders are not stored)
if os.path.exists(R("readable_preds_v2.parquet")):
    Rd = pd.read_parquet(R("readable_preds_v2.parquet")); Rd["id"] = Rd.id.astype(str); H, D = [], []
    for d, g in Rd.groupby("day"):
        h = hk(g.sort_values(["b", "id"], ascending=[False, True]).id.tolist(), d)
        if h is not None: H.append(h); D.append(d)
    rows.append(row("0005", "readable_v2", "explanation model backtest (readable v2 stumps, no th_n_pre), month-forward", H, D, "results/readable_preds_v2.parquet"))
# 00:05 live rows by producing model (scoreboard orders, published 00:05 rows)
SO = json.load(open(R("web/scoreboard_orders.json")))["rows"]
def live_model(d): return "old full model" if d <= "2026-11-12" else "clean_nosite" if d <= "2026-11-14" else "arm2"
by = {}
for r in SO:
    if r["point"] == "0005" and r["method"] == "published" and r["order"]:
        by.setdefault(live_model(r["day"]), []).append(r)
for m, rs in by.items():
    for lab, keep in (("live + late writes", lambda r: True), ("live writes only", lambda r: r["source"] == "live")):
        rr = [r for r in rs if keep(r)]
        H = [hk(r["order"], r["day"]) for r in rr]; D = [r["day"] for r in rr if hk(r["order"], r["day"]) is not None]
        if D: rows.append(row("0005", m, f"published 00:05 rows ({lab})", H, D, "results/web/scoreboard_orders.json"))
# before-reveal: LODO replay orders incl. unranked launches
for f, model, key in (("hybrid_lodo_ku_orders.json", "hybrid_vm (live prior)", "lodo_hybrid"), ("hybrid_lodo_ku_fixedprior_orders.json", "hybrid_vm (fixed prior)", "lodo_hybrid"),
                      ("hybrid_lodo_ku_orders.json", "hidden_rank_only", "hidden")):
    if not os.path.exists(R(f)): continue
    O = json.load(open(R(f)))["days"]; H, D = [], []
    for d, v in sorted(O.items()):
        h = hk(v[key], d)
        if h is not None: H.append(h); D.append(d)
    rows.append(row("prereveal", model, "leave-one-day-out replay, 03:00 recorder read, unranked launches kept in the order", H, D, f"results/{f}"))
# weekly board (b): predicted entrants inserted, all board days (truth = official weekly_rank; its own rule)
if os.path.exists(R("weekly_board_pred_days.csv")):
    Wb = pd.read_csv(R("weekly_board_pred_days.csv"))
    rows.append({"point": "weekly", "model": "board (b) + predicted entrants", "method": "held data, 29 weeks, every board day",
                 "top3": round(Wb.b_3.mean() * 100, 1), "top5": round(Wb.b_5.mean() * 100, 1), "top10": round(Wb.b_10.mean() * 100, 1),
                 "n_days": int(len(Wb)), "first_day": Wb.day.min(), "last_day": Wb.day.max(), "rule": "share of the board's top k in the official weekly top k",
                 "source": "results/weekly_board_pred_days.csv"})
rows.append({"point": "monthly", "model": "board", "method": "not yet scored (first score Dec 1)", "top3": None, "top5": None, "top10": None, "n_days": 0,
             "first_day": None, "last_day": None, "rule": "official monthly_rank", "source": None})
out = {"computed_at": pd.Timestamp.now(tz="UTC").isoformat(), "truth": "warehouse launches.daily_rank (final), rank <= k; unranked picks are misses", "rows": rows}
p = R("web/north_star_table.json"); json.dump(out, open(p, "w"), indent=1)
subprocess.run(["gsutil", "-q", "cp", p, "gs://usersim-bakeoff-347838016394/usersim_sim/results/web/north_star_table.json"], check=False)
for r in rows: print(f"{r['point']:9s} {r['model']:32s} {r['top3']} / {r['top5']} / {r['top10']}  n={r['n_days']} {r['first_day']}..{r['last_day']}")
