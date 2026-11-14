import sys, glob, json; sys.path.insert(0, "/home/user/UserSim/experiments"); import numpy as np, pandas as pd
from pipeline import warehouse as W
rng = np.random.default_rng(0); SP = sys.argv[1]
L = W.table("launches", do_sync=True).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L = L[L.daily_rank.notna()]
RK = {d: dict(zip(g.id, g.daily_rank.astype(float))) for d, g in L.groupby("day")}
A = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/rb/asof3/*.parquet")]); A["id"] = A.id.astype(str)
def hits(o, d): t = sorted(RK[d], key=lambda i: RK[d][i]); return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
R = []
for d, g in A.groupby("day"):
    if d in RK and len(RK[d]) >= 10:
        R.append({"day": d, **{c: hits(g.sort_values([c, "id"], ascending=[False, True]).id.tolist(), d) for c in ("pred_arm2", "pred_arm3")}})
X2 = np.array([r["pred_arm2"] for r in R]); X3 = np.array([r["pred_arm3"] for r in R]); D = X3 - X2
bs = np.array([D[rng.integers(0, len(D), len(D))].mean(0) for _ in range(5000)])
out = {"n_days": len(R), "arm2 at 00:05": X2.mean(0).round(1).tolist(), "arm3 at 00:05": X3.mean(0).round(1).tolist(),
       "arm3 - arm2": [[round(D[:, k].mean(), 1), round(np.percentile(bs[:, k], 2.5), 1), round(np.percentile(bs[:, k], 97.5), 1)] for k in range(3)],
       "days arm3 better / worse / same, top 10": [int((D[:, 2] > 0).sum()), int((D[:, 2] < 0).sum()), int((D[:, 2] == 0).sum())],
       "days arm3 better / worse / same, top 3": [int((D[:, 0] > 0).sum()), int((D[:, 0] < 0).sum()), int((D[:, 0] == 0).sum())], "per_day": R}
json.dump(out, open(f"{SP}/rb/asof3_score.json", "w"), indent=1); print(json.dumps({k: v for k, v in out.items() if k != "per_day"}))
