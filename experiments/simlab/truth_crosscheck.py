"""Nightly cross-check (orchestrator 20:54Z Nov 14): recompute PH ops' north-star rows (results/web/north_star_table.json) from
results/web/truth_daily.json with the published rule, from every source order E5 can read; print MISMATCH lines (exit 3) when a row
differs by > TOL points at any k or in n_days. Rows whose source orders are VM-only are listed as 'not checkable here'. Ids/counts only.
  python truth_crosscheck.py <SP>   -> <SP>/truth/crosscheck.json (+ tmp/e5/website/truth_crosscheck.json)"""
import json, os, subprocess, sys
import pandas as pd
SP = sys.argv[1]; B = "gs://usersim-bakeoff-347838016394/usersim_sim"; TOL = 0.15
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
NS = json.loads(gcat(f"{B}/results/web/north_star_table.json"))
TD = json.loads(gcat(f"{B}/results/web/truth_daily.json") or open(f"{SP}/truth/truth_daily.json").read())["days"]


def score(orders):
    H = []
    for d, o in sorted(orders.items()):
        t = TD.get(d)
        if not t or t["status"] != "counts": continue
        R = t["ranks"]; H.append([100 * sum(1 for i in o[:k] if R.get(str(i), 99) <= k) / k for k in (3, 5, 10)])
    if not H: return None
    m = pd.DataFrame(H).mean(); return {"top3": round(m[0], 1), "top5": round(m[1], 1), "top10": round(m[2], 1), "n_days": len(H)}


src = {}
X = pd.read_parquet(f"{SP}/a2x/history_retrain_decomp_preds_arm2.parquet"); X["id"] = X.id.astype(str); X["day"] = X.day.astype(str).str[:10]
for col, model in (("both", "arm2"), ("pure", "clean_nosite")):
    src[("0005", model, "backtest, month-forward Apr-Oct 2026, 5 seeds")] = {d: g.sort_values([col, "id"], ascending=[False, True]).id.tolist() for d, g in X.groupby("day")}
RO = json.load(open(f"{SP}/a2x/replay_orders_345.json"))["days"]
for key, model in (("hybrid", "hybrid_vm (live prior)"), ("hybrid_fixed", "hybrid_vm (fixed prior)"), ("hidden", "hidden_rank_only")):
    src[("prereveal", model, "")] = {d: v[key] for d, v in RO.items() if key in v}
SO = json.loads(gcat(f"{B}/results/web/scoreboard_orders.json") or "{}").get("rows", [])
for model, lo, hi in (("old full model", "2026-10-25", "2026-11-12"), ("clean_nosite", "2026-11-13", "2026-11-14")):
    for lab, ok in (("live + late writes", lambda r: True), ("live writes only", lambda r: r.get("source") == "live")):
        src[("0005", model, f"published 00:05 rows ({lab})")] = {r["day"]: [str(i) for i in r["order"]] for r in SO
                                                                 if r.get("point") == "0005" and r.get("method") == "published" and lo <= r["day"] <= hi and ok(r)}
out, bad = [], []
for r in NS["rows"]:
    k = next((k for k in src if k[0] == r["point"] and k[1] == r["model"] and k[2] in r["method"]), None)
    if k is None: out.append({"row": [r["point"], r["model"], r["method"]], "status": "not checkable here (source orders not readable by E5)", "source": r.get("source")}); continue
    me = score(src[k]); pub = {x: r.get(x) for x in ("top3", "top5", "top10", "n_days")}
    diff = me is None or me["n_days"] != pub["n_days"] or any(pub[x] is None or abs(me[x] - pub[x]) > TOL for x in ("top3", "top5", "top10"))
    out.append({"row": [r["point"], r["model"], r["method"]], "published": pub, "recomputed_from_truth_daily": me, "status": "MISMATCH" if diff else "ok"})
    if diff: bad.append(out[-1])
J = {"checked_at": pd.Timestamp.now(tz="UTC").isoformat(), "north_star_computed_at": NS.get("computed_at"), "tolerance_points": TOL, "rows": out,
     "n_mismatch": len(bad)}
os.makedirs(f"{SP}/truth", exist_ok=True); p = f"{SP}/truth/crosscheck.json"; json.dump(J, open(p, "w"), indent=1)
subprocess.run(["gsutil", "-q", "cp", p, f"{B}/tmp/e5/website/truth_crosscheck.json"])
for b in bad: print("MISMATCH", json.dumps(b))
print(json.dumps({"n_rows": len(out), "ok": sum(o["status"] == "ok" for o in out), "mismatch": len(bad), "not_checkable": sum(o["status"].startswith("not") for o in out)}))
sys.exit(3 if bad else 0)
