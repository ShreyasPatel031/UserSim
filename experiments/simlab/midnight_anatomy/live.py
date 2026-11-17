import json, glob, sys, numpy as np, pandas as pd
SP = sys.argv[1]; OUT = f"{SP}/mna/out"; rng = np.random.default_rng(0)
TD = json.load(open(f"{SP}/pra/truth_daily.json"))["days"]; R = pd.read_parquet(f"{OUT}/arm3_oos_contrib.parquet"); R["id"] = R.id.astype(str)
H = pd.read_parquet(f"{SP}/pra/out/launch_rows.parquet"); H["id"] = H.id.astype(str)
rows = []
for f in sorted(glob.glob(f"{SP}/mna/f5/*.json")):
    d = json.load(open(f)); day = d["day"]
    if day < "2026-10-29" or day not in TD: continue
    tr = {str(k): v for k, v in TD[day]["ranks"].items()}; real = lambda k: {i for i, r in tr.items() if r <= k}
    sc = lambda order: [len(set(order[:k]) & real(k)) / k * 100 for k in (3, 5, 10)]
    pub = [str(x["id"]) for x in sorted(d["forecast"], key=lambda x: x["predicted_rank"])]
    row = {"day": day, "published_model": "arm 2" if day >= "2026-11-14" else "earlier 00:05 model (clean_nosite)", "published": sc(pub)}
    g = R[R.day == day]
    if len(g) >= 10: row["arm2_rebuild"] = sc(list(g.sort_values("pred2", ascending=False).id)); row["arm3_rebuild"] = sc(list(g.sort_values("pred3", ascending=False).id))
    h = H[H.day == day]
    if len(h): row["before_reveal"] = sc(list(h.sort_values("pred_rank").id))
    rows.append(row)
L = pd.DataFrame(rows)
def agg(col, sub=None):
    S = L if sub is None else L[sub]; S = S[S[col].notna()]; A = np.array(S[col].tolist())
    if not len(A): return None
    return {"days": len(A), **{f"top{k}": round(float(A[:, j].mean()), 1) for j, k in enumerate((3, 5, 10))}}
O = {"per_day": rows, "published, all live days": agg("published"), "published arm 2 days (Nov 14-15)": agg("published", L.day >= "2026-11-14"),
     "arm 2 rebuild, live days to Nov 12": agg("arm2_rebuild"), "arm 3 rebuild, live days to Nov 12": agg("arm3_rebuild"), "before-reveal replay, Nov 2-15": agg("before_reveal")}
both = L[L.arm3_rebuild.notna() & L.before_reveal.notna()]
O["same days (Nov 2-12, rebuild and replay)"] = {c: agg(c, L.day.isin(both.day)) for c in ("published", "arm2_rebuild", "arm3_rebuild", "before_reveal")}
json.dump(O, open(f"{OUT}/live_days.json", "w"), indent=1, default=str); print(json.dumps({k: v for k, v in O.items() if k != "per_day"}, indent=1))
