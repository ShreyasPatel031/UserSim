# copy of the VM run script (run from ~/w/experiments/ph_predict with PYTHONPATH=~/w/mk:.)
"""C: second-stage re-ranker on arm 2's top 10 (orchestrator 20:24Z Nov 13). Month-forward ridge on earlier months' top-10 sets,
target z(log votes) within the set. Inputs: z(arm2 score) within set + readable flags. Compared paired vs arm 2 (both), 214 days."""
import sys, os, json; sys.path[:0] = ['..', '.']
import features as F, run as RN, pandas as pd, numpy as np
from sklearn.linear_model import Ridge
df = RN.load_llm(F.build()); df["id"] = df.id.astype(str)
A = pd.read_parquet("results/history_retrain_decomp_preds_arm2.parquet"); A["id"] = A.id.astype(str)
th = pd.read_parquet(os.path.expanduser("~/w/h25/th_n_pre_2026.parquet")); th["id"] = th.id.astype(str)
keep = ["id", "logv", "hist_hunter_n", "hist_hunter_rel", "ph_self_hunted", "llm_brand", "llm_pitch", "ph_n_makers", "ph_hunter_age_d"]
A = A.dropna(subset=["dailyRank", "both"]).merge(df[[c for c in keep if c in df]], on="id", how="left").merge(th, on="id", how="left")
A["th_n_pre"] = A.th_n_pre.fillna(0); A["mon"] = A.day.str[:7]
A["first_hunt"] = (A.hist_hunter_n.fillna(0) == 0).astype(float); A["self"] = A.ph_self_hunted.fillna(0).astype(float)
A["brand2"] = (A.llm_brand.fillna(0) >= 2).astype(float); A["lnpre"] = np.log1p(A.th_n_pre)
A = A.sort_values(["day", "both", "id"], ascending=[True, False, True]); A["r"] = A.groupby("day").cumcount() + 1
T = A[A.r <= 10].copy()
zf = lambda s: (s - s.mean()) / s.std() if s.std() > 0 else s * 0.0
for c in ("both", "lnpre", "llm_pitch", "hist_hunter_rel"):
    T["z_" + c] = T.groupby("day")[c].transform(zf).fillna(0)
T["y"] = T.groupby("day").logv.transform(zf)
T["ft_x_s"] = T.first_hunt * T.z_both; T["ft_self"] = T.first_hunt * T.self
VAR = {"safe: score + first-time hunter + th_n_pre + pitch + brand>=2": ["z_both", "first_hunt", "ft_x_s", "z_lnpre", "z_llm_pitch", "brand2"],
       "safe + hunter history": ["z_both", "first_hunt", "ft_x_s", "z_lnpre", "z_llm_pitch", "brand2", "z_hist_hunter_rel"],
       "+ self-hunted (LEAKY: needs named makers)": ["z_both", "first_hunt", "ft_x_s", "z_lnpre", "z_llm_pitch", "brand2", "self", "ft_self"]}
def hits(o, t): return [len(set(o[:k]) & set(t[:k])) / k * 100 for k in (3, 5, 10)]
truth = {d: g.sort_values("dailyRank").id.tolist() for d, g in A.groupby("day")}
base = {d: g.id.tolist() for d, g in A.groupby("day")}
days = sorted(T.day.unique()); P0 = np.array([hits(base[d], truth[d]) for d in days])
rng = np.random.default_rng(0); out = {"days": len(days), "base": P0.mean(0).round(1).tolist(), "first_hunt_share_top10": round(T.first_hunt.mean(), 3), "self_share": round(T.self.mean(), 3)}
for nm, cols in VAR.items():
    P, W = [], {}
    for d in days:
        g = T[T.day == d]; m = g.mon.iloc[0]
        if m not in W:
            tr = T[T.mon < m]; W[m] = Ridge(alpha=3.0).fit(tr[cols], tr.y) if len(tr) else None
        o = base[d] if W[m] is None else g.assign(s=W[m].predict(g[cols])).sort_values(["s", "id"], ascending=[False, True]).id.tolist() + base[d][10:]
        P.append(hits(o, truth[d]))
    P = np.array(P); res = {}
    for lab, sl in (("all", slice(None)), ("last107", slice(-107, None))):
        dP = P[sl] - P0[sl]; b = np.array([dP[rng.integers(0, len(dP), len(dP))].mean(0) for _ in range(4000)])
        res[lab] = {"lines": P[sl].mean(0).round(1).tolist(), "diff": dP.mean(0).round(1).tolist(), "lo": np.percentile(b, 2.5, 0).round(1).tolist(), "hi": np.percentile(b, 97.5, 0).round(1).tolist()}
    res["weights_last"] = dict(zip(cols, np.round(W[max(W)].coef_, 3).tolist()))
    out[nm] = res
print(json.dumps(out, indent=1))
