import json, glob, collections, numpy as np, sys
SP = sys.argv[1]; R = [json.load(open(f)) for f in sorted(glob.glob(f"{SP}/parity/2026-*.json"))]
cols = collections.defaultdict(list); setc = collections.defaultdict(list); alerts = collections.Counter(); allc = []
for r in R:
    for c, v in r["columns"].items(): cols[c].append(v)
    for c, v in r["set change top3/5/10 (members changed) per swapped column (only nonzero)"].items(): setc[c].append(v)
    for c in r["UNEXPECTED differing columns"]: alerts[c] += 1
    allc.append(r["set change, all live columns together"])
out = {"nights": len(R), "rows in both": sum(r["in both"] for r in R), "only live / only backtest": [sum(r["only live"] for r in R), sum(r["only backtest"] for r in R)],
       "columns": {c: {"share_equal (mean over nights)": round(float(np.mean([x["share_equal"] for x in v])), 3), "nights differing": sum(x["share_equal"] < 1 for x in v),
                       "mean_abs_diff_sd": round(float(np.nanmean([x["mean_abs_diff_sd"] or 0 for x in v])), 3), "expected": v[0].get("expected")} for c, v in cols.items()},
       "unexpected columns: nights alerted": dict(alerts.most_common()),
       "set change per swapped column (mean members changed top3/5/10 over nights)": {c: np.round(np.sum(v, axis=0) / len(R), 2).tolist() for c, v in setc.items()},
       "set change all live columns together (mean, max top3/5/10)": [np.round(np.mean(allc, axis=0), 2).tolist(), np.max(allc, axis=0).tolist()]}
json.dump(out, open(f"{SP}/parity/parity_summary.json", "w"), indent=1, default=float)
diff = {c: v for c, v in out["columns"].items() if v["nights differing"]}
print(json.dumps({k: v for k, v in out.items() if k != "columns"}, default=float)); print(json.dumps(diff, default=float))
