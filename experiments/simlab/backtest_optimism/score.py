"""Score opt.py outputs. python score.py <out dir> <snapshot data dir> -> result.json here."""
import glob, json, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUT, DATA = sys.argv[1:3]; rng = np.random.default_rng(0)
VIEWS = ["V0_asof", "V1_text", "V2_makers", "V3_hunter", "V4_rest", "V5_reread"]; K = (3, 5, 10)
P = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f"{OUT}/*.parquet"))]); P["id"] = P.id.astype(str)
rows = []
for d, g in P.groupby("day"):
    T = pd.DataFrame(json.load(open(f"{DATA}/days/{d}.json")))[["id", "dailyRank"]]; T["id"] = T.id.astype(str); T = T.dropna()
    if len(T) < 10: continue
    tr = {k: set(T[T.dailyRank <= k].id) for k in K}
    for v in VIEWS:
        h = g[g.view == v]
        for arm in ("arm2", "arm3"):
            rows.append({"day": d, "view": v, "arm": arm, **{f"top{k}": len(set(h.nlargest(k, arm).id) & tr[k]) / k * 100 for k in K}})
S = pd.DataFrame(rows); days = sorted(S.day.unique())
def ci(v):
    b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(4000)]; return [round(float(v.mean()), 1), round(float(np.percentile(b, 2.5)), 1), round(float(np.percentile(b, 97.5)), 1)]
def vec(v, arm, k): return S[(S.view == v) & (S.arm == arm)].set_index("day").loc[days, f"top{k}"].values
O = {"days": len(days), "day_list": days, "levels": {}, "gap_reread_minus_asof": {}, "steps": {}, "arm3_minus_arm2": {}}
for arm in ("arm2", "arm3"):
    O["levels"][arm] = {v: {f"top{k}": ci(vec(v, arm, k)) for k in K} for v in ("V0_asof", "V5_reread")}
    O["gap_reread_minus_asof"][arm] = {f"top{k}": ci(vec("V5_reread", arm, k) - vec("V0_asof", arm, k)) for k in K}
    O["steps"][arm] = {f"{a} -> {b}": {f"top{k}": ci(vec(b, arm, k) - vec(a, arm, k)) for k in K} for a, b in zip(VIEWS[:-1], VIEWS[1:])}
for v in ("V0_asof", "V5_reread"):
    O["arm3_minus_arm2"][v] = {f"top{k}": ci(vec(v, "arm3", k) - vec(v, "arm2", k)) for k in K}
# line-up change counts per day
lc = []
for d in days:
    a = {str(r["id"]) for r in json.load(open(f"{DATA}/today/{d}.json"))}; b = pd.DataFrame(json.load(open(f"{DATA}/days/{d}.json")))
    b["id"] = b.id.astype(str); top10 = set(b[b.dailyRank <= 10].id)
    lc.append({"day": d, "n_0005": len(a), "n_reread": len(b), "added": len(set(b.id) - a), "removed": len(a - set(b.id)), "final_top10_absent_at_0005": len(top10 - a)})
O["lineup_changes"] = lc; O["final_top10_absent_at_0005_total"] = int(sum(x["final_top10_absent_at_0005"] for x in lc))
json.dump(O, open(os.path.join(HERE, "result.json"), "w"), indent=1); print(json.dumps(O, indent=1))
