import sys, os, json, glob, subprocess; sys.path.insert(0, "/home/user/UserSim/experiments"); import numpy as np, pandas as pd
from pipeline import warehouse as W
rng = np.random.default_rng(0); SP = sys.argv[1]
L = W.table("launches", do_sync=True).sort_values("updated_at").drop_duplicates("id", keep="last"); L["id"] = L.id.astype(str); L = L[L.daily_rank.notna()]
RK = {d: dict(zip(g.id, g.daily_rank.astype(float))) for d, g in L.groupby("day")}
A = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{SP}/rb/asof/*.parquet")]); A["id"] = A.id.astype(str)
gcat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True).stdout
def hits(order, d): t = sorted(RK[d], key=lambda i: RK[d][i]); return [len(set(order[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
rows = []
for d in sorted(A.day.unique()):
    if d not in RK: continue
    nr = len(RK[d]); r = {"day": d, "n_ranked": nr}
    for mode in ("asof", "final"):
        g = A[(A.day == d) & (A["mode"] == mode)]
        if g.empty: continue
        r[f"n_{mode}"] = len(g)
        for col, nm in (("pred_clean", "clean"), ("pred_arm2", "arm2")):
            r[f"{nm}_{mode}"] = hits(g.sort_values([col, "id"], ascending=[False, True]).id.tolist(), d)
    raw = gcat(f"gs://usersim-bakeoff-347838016394/usersim_sim/results/web/forecast_0005/{d}.json")
    if raw:
        J = json.loads(raw); F = pd.DataFrame(J["forecast"]); F["id"] = F.id.astype(str)
        r["published"] = hits(F.sort_values("predicted_rank").id.tolist(), d); r["published_run_at"] = J.get("run_updated_at")
    rows.append(r)
R = pd.DataFrame(rows); keep = R[R.n_ranked >= 10]
def m(col, df):
    df = df[df[col].map(lambda v: isinstance(v, list))]; X = np.array(df[col].tolist()); b = np.array([X[rng.integers(0, len(X), len(X))].mean(0) for _ in range(3000)]); return [[round(X[:, k].mean(), 1), round(np.percentile(b[:, k], 2.5), 1), round(np.percentile(b[:, k], 97.5), 1)] for k in range(3)] + [len(X)]
def pdiff(a, b, df):
    df = df[df[a].map(lambda v: isinstance(v, list)) & df[b].map(lambda v: isinstance(v, list))]; X = np.array(df[b].tolist()) - np.array(df[a].tolist()); bb = np.array([X[rng.integers(0, len(X), len(X))].mean(0) for _ in range(3000)]); return [[round(X[:, k].mean(), 1), round(np.percentile(bb[:, k], 2.5), 1), round(np.percentile(bb[:, k], 97.5), 1)] for k in range(3)] + [len(X)]
out = {"days_scored (>=10 ranked)": keep.day.tolist(), "excluded short": R[R.n_ranked < 10].day.tolist(), "n": len(keep)}
for c in ("arm2_asof", "clean_asof", "arm2_final", "clean_final"): out[c] = m(c, keep)
out["arm2 - clean, asof"] = pdiff("clean_asof", "arm2_asof", keep); out["arm2 - clean, final"] = pdiff("clean_final", "arm2_final", keep)
out["00:05 penalty arm2 (asof - final)"] = pdiff("arm2_final", "arm2_asof", keep); out["00:05 penalty clean (asof - final)"] = pdiff("clean_final", "clean_asof", keep)
P = keep[keep.published.map(lambda v: isinstance(v, list))] if "published" in keep else keep.iloc[:0]
out["published days"] = P.day.tolist(); out["published"] = m("published", P) if len(P) else None
if len(P): out["clean_asof on published days"] = m("clean_asof", P); out["published - clean_asof"] = pdiff("clean_asof", "published", P)
out["per_day"] = R.to_dict("records")
json.dump(out, open(f"{SP}/rb/asof_score.json", "w"), indent=1, default=str); print(json.dumps({k: v for k, v in out.items() if k != "per_day"}, default=str))
