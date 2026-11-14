import sys, glob, json; sys.path.insert(0, "/home/user/UserSim/experiments"); import numpy as np, pandas as pd
from pipeline import warehouse as W
rng = np.random.default_rng(0); SP = sys.argv[1]
L = W.table("launches", do_sync=False).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L = L[L.daily_rank.notna()]
RK = {d: dict(zip(g.id, g.daily_rank.astype(float))) for d, g in L.groupby("day")}
A = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/rb/asof/*.parquet")]); A["id"] = A.id.astype(str)
def hits(o, d): t = sorted(RK[d], key=lambda i: RK[d][i]); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
out, per = {}, []
for col, nm in (("pred_clean", "clean_nosite"), ("pred_arm2", "arm 2")):
    R = []
    for d in sorted(A.day.unique()):
        c = A[(A.day == d) & (A["mode"] == "asof")]; s = A[(A.day == d) & (A["mode"] == "asof_stale")]
        if c.empty or s.empty or d not in RK or len(RK[d]) < 10: continue
        oc = c.sort_values([col, "id"], ascending=[False, True]).id.tolist(); os_ = s.sort_values([col, "id"], ascending=[False, True]).id.tolist()
        R.append({"day": d, "clean": hits(oc, d), "stale": hits(os_, d), "top3 picks changed": 3 - len(set(oc[:3]) & set(os_[:3])), "top10 picks changed": 10 - len(set(oc[:10]) & set(os_[:10])), "top1 changed": int(oc[0] != os_[0])})
    X = np.array([r["stale"] for r in R]) - np.array([r["clean"] for r in R]); b = np.array([X[rng.integers(0, len(X), len(X))].mean(0) for _ in range(5000)])
    out[nm] = {"n_days": len(R), "clean (as-of, only today/D)": np.array([r["clean"] for r in R]).mean(0).round(1).tolist(), "stale (as the VM ran)": np.array([r["stale"] for r in R]).mean(0).round(1).tolist(),
               "stale - clean (bug cost)": [[round(X[:, k].mean(), 1), round(np.percentile(b[:, k], 2.5), 1), round(np.percentile(b[:, k], 97.5), 1)] for k in range(3)],
               "top-3 picks changed per night (mean, max)": [round(np.mean([r["top3 picks changed"] for r in R]), 2), max(r["top3 picks changed"] for r in R)],
               "top-10 picks changed per night (mean, max)": [round(np.mean([r["top10 picks changed"] for r in R]), 2), max(r["top10 picks changed"] for r in R)],
               "nights with a different #1": sum(r["top1 changed"] for r in R), "per night": R}
json.dump(out, open(f"{SP}/rb/stale_score.json", "w"), indent=1, default=float); print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "per night"} for k, v in out.items()}, default=float))
