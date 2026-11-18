"""Audit of the site's confidence flag "#1 / #2 / #3 picks finish top 3 90.3% / 57.0% / 41.1%" (measured Nov 11 on the old full
model; orchestrator 23:06Z Nov 14). Recomputed per published model on the single truth source.

Truth: results/web/truth_daily.json (E5: first warehouse part after the PT close); a day counts if >= 10 ranked; a pick that is
unranked counts as a miss. Rate = share of days on which our pick #i finished with final daily rank <= 3 (also <= 5, <= 10).
Orders: arm 2 = month-forward backtest Apr-Oct 2026 (history_retrain_decomp_preds_arm2.parquet 'both', 5 seeds, as published);
arm 3 and arm 2 (20 seeds) = pre-registered harness (arm3_vs_arm2_preds.parquet), 2026 and 2025; old full model = published 00:05
live rows (scoreboard_orders.json, days <= Nov 12). Ties broken by id. Intervals: day bootstrap 95% (4000).
usage: python conf_flag_audit.py -> results/conf_flag_audit.{json,md}"""
import json, os, subprocess
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); R = lambda p: os.path.join(HERE, "results", p)
T = json.loads(subprocess.run(["gsutil", "cat", "gs://usersim-bakeoff-347838016394/usersim_sim/results/web/truth_daily.json"],
                              capture_output=True, text=True, check=True).stdout)["days"]
TR = {d: {str(i): r for i, r in v["ranks"].items()} for d, v in T.items() if len(v.get("ranks", {})) >= 10}


def picks_hits(orders, truth=None):
    """orders: {day: [ids best first]} -> array days x pick(1..3) x k(3,5,10)"""
    H, D = [], []; truth = truth or TR
    for d, o in sorted(orders.items()):
        t = truth.get(d)
        if t is None or len(o) < 3: continue
        H.append([[1.0 if t.get(str(o[i]), 999) <= k else 0.0 for k in (3, 5, 10)] for i in range(3)]); D.append(d)
    return np.array(H), D


def summ(H, D, B=4000):
    rng = np.random.default_rng(0); n = len(H); bs = np.array([H[rng.integers(0, n, n)].mean(0) for _ in range(B)])
    lo, hi = np.percentile(bs, 2.5, 0), np.percentile(bs, 97.5, 0)
    out = {"n_days": n, "first_day": D[0], "last_day": D[-1]}
    for i in range(3):
        for j, k in enumerate((3, 5, 10)):
            out[f"pick{i + 1}_top{k}"] = [round(100 * H[:, i, j].mean(), 1), round(100 * lo[i, j], 1), round(100 * hi[i, j], 1)]
    return out


def from_frame(P, col):
    return {d: g.sort_values([col, "id"], ascending=[False, True]).id.astype(str).tolist() for d, g in P.groupby("day")}


res = {}
A = pd.read_parquet(R("history_retrain_decomp_preds_arm2.parquet")); A["id"] = A.id.astype(str)
res["arm2 (published), backtest Apr-Oct 2026, 5 seeds"] = summ(*picks_hits(from_frame(A, "both")))
P = pd.read_parquet(R("arm3_vs_arm2_preds.parquet")); P["id"] = P.id.astype(str)
for yr in ("2026", "2025"):
    Q = P[P.year == yr]
    for col in ("arm3", "arm2"):
        if yr == "2026":
            res[f"{col}, pre-registered harness {yr}, 20 seeds"] = summ(*picks_hits(from_frame(Q, col)))
        else:   # truth_daily.json covers 2026 only: 2025 uses the harness's stored dailyRank (flagged)
            t25 = {d: {i: r for i, r in zip(g.id, g.dailyRank) if pd.notna(r)} for d, g in Q.groupby("day")}
            t25 = {d: v for d, v in t25.items() if len(v) >= 10}
            res[f"{col}, pre-registered harness {yr}, 20 seeds (truth: stored dailyRank, not truth_daily.json)"] = summ(*picks_hits(from_frame(Q, col), t25))
SO = json.load(open(R("web/scoreboard_orders.json")))["rows"]
old = {r["day"]: [str(x) for x in r["order"]] for r in SO if r.get("point") in (None, "0005") and r.get("day", "") <= "2026-11-12" and r.get("order")}
if old:
    res["old full model, published 00:05 live rows"] = summ(*picks_hits(old))
md = ["# Confidence flag audit: share of days our pick #1 / #2 / #3 finished in the final top 3", "",
      "Truth: truth_daily.json (>= 10 ranked; unranked picks = misses). 95% day-bootstrap intervals. Site figure: 90.3 / 57.0 / 41.1 (old full model, Nov 11).", "",
      "| model | days | #1 top 3 | #2 top 3 | #3 top 3 | #1 top 5 | #1 top 10 |", "|---|---|---|---|---|---|---|"]
c = lambda v: f"{v[0]} [{v[1]}, {v[2]}]"
for m, s in res.items():
    md.append(f"| {m} | {s['n_days']} | {c(s['pick1_top3'])} | {c(s['pick2_top3'])} | {c(s['pick3_top3'])} | {c(s['pick1_top5'])} | {c(s['pick1_top10'])} |")
    print(m, s["n_days"], s["pick1_top3"], s["pick2_top3"], s["pick3_top3"])
json.dump({"method": __doc__, "results": res}, open(R("conf_flag_audit.json"), "w"), indent=1)
open(R("conf_flag_audit.md"), "w").write("\n".join(md) + "\n")
