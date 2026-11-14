"""Score e5_makers0.py (pre-registered results_reports/PREREG_makers0_nan.md). Truth: 2025 = dailyRank in the history data; 2026 = results/web/
truth_daily.json (first part after close). Days with >= 10 ranked; hits@k = our top k with rank <= k (unranked = miss). Paired (fix - arm2) per
day, DAY bootstrap 2000. Subset: launches with an empty maker list, change in predicted within-day rank (fix - arm2; negative = moved up).
    python score_makers0.py <preds parquet> <truth_daily.json> <out json>"""
import json, sys
import numpy as np, pandas as pd
PQ, TDP, OUT = sys.argv[1:4]; rng = np.random.default_rng(0)
D = pd.read_parquet(PQ); D["id"] = D.id.astype(str); D["day"] = D.day.astype(str).str[:10]
TD = json.load(open(TDP))["days"]
def truth(day, g):
    if g.year.iloc[0] == "2025": return {i: r for i, r in zip(g.id, g.dailyRank) if pd.notna(r)}
    t = TD.get(day); return {i: r for i, r in (t or {}).get("ranks", {}).items()} if t else {}
res, sub = {}, []
for yr, Y in D.groupby("year"):
    rows = []
    for day, g in Y.groupby("day"):
        T = truth(day, g)
        if len(T) < 10: continue
        r = {"day": day}
        for col in ("arm2", "fix"):
            o = g.sort_values([col, "id"], ascending=[False, True]).id.tolist()
            for k in (3, 5, 10): r[f"{col}_{k}"] = 100 * sum(1 for i in o[:k] if T.get(i, 99) <= k) / k
        rows.append(r)
        z = g[g.zero_makers]
        if len(z):
            ra = g.arm2.rank(ascending=False); rf = g.fix.rank(ascending=False)
            for i in z.index: sub.append({"year": yr, "d_rank": float(rf[i] - ra[i]), "finished": T.get(g.loc[i, "id"])})
    R = pd.DataFrame(rows); out = {"days": int(len(R)), "launches": int(Y[Y.day.isin(R.day)].shape[0]), "zero_maker_launches": int(Y[Y.day.isin(R.day)].zero_makers.sum())}
    for k in (3, 5, 10):
        d = (R[f"fix_{k}"] - R[f"arm2_{k}"]).values; bs = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
        out[f"top{k}"] = {"arm2": round(R[f"arm2_{k}"].mean(), 1), "fix": round(R[f"fix_{k}"].mean(), 1),
                          "fix - arm2 [95% day bootstrap]": [round(float(d.mean()), 2), round(float(np.percentile(bs, 2.5)), 2), round(float(np.percentile(bs, 97.5)), 2)]}
    res[yr] = out
S = pd.DataFrame(sub)
for yr, g in S.groupby("year"):
    res[yr]["zero-maker launches: predicted within-day rank change (fix - arm2; negative = moved up)"] = {
        "n": int(len(g)), "mean": round(float(g.d_rank.mean()), 2), "median": float(g.d_rank.median()), "share moved up": round(float((g.d_rank < 0).mean()), 3),
        "share unchanged": round(float((g.d_rank == 0).mean()), 3)}
lo = {f"{y} top{k}": res[y][f"top{k}"]["fix - arm2 [95% day bootstrap]"][1] for y in res for k in (3, 5, 10)}
res["decision (pre-registered: adopt if all six lower bounds > -1.0)"] = {"lower bounds": lo, "adopt": all(v > -1.0 for v in lo.values()),
    "clear gain at top 3 in both years": all(res[y]["top3"]["fix - arm2 [95% day bootstrap]"][1] > 0 for y in res if y in ("2025", "2026"))}
json.dump(res, open(OUT, "w"), indent=1, default=float); print(json.dumps(res, default=float, indent=1))
