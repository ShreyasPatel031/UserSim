import json, numpy as np, pandas as pd, glob, os, sys
from scipy.stats import spearmanr
sys.path.insert(0, "."); from simlab import store
R = store.RAW
def load(p):
    return pd.DataFrame.from_dict(json.load(open(f"{R}/{p}_features.json")), orient="index").rename_axis("id").reset_index()
C = pd.read_parquet("ph_predict/results/ctrl_preds.parquet"); C["id"] = C.id.astype(str); C["resid"] = C.logv - C.fixed
A = C.merge(load("psn"), on="id").merge(load("psp"), on="id").merge(load("pst"), on="id")
for p in ("psn", "psp", "pst"):
    for c in ("ev", "share", "top3"):
        if f"{p}_{c}" in A: A[f"{p}_{c}"] = np.log1p(A[f"{p}_{c}"])
A["lift_page"] = A.psp_ev - A.psn_ev; A["lift_taste"] = A.pst_ev - A.psp_ev; A["lift_both"] = A.pst_ev - A.psn_ev
if "pst_share" in A: A["lift_taste_share"] = A.pst_share - A.psn_ev
rng = np.random.default_rng(0); res = {"n": len(A)}
for col in [c for c in A if c.startswith(("lift_", "pst_", "psp_ev", "psn_ev"))]:
    per = np.array([spearmanr(g[col], g.resid).correlation for _, g in A.groupby("day") if len(g) >= 8 and g[col].nunique() > 1]); per = per[~np.isnan(per)]
    bs = [rng.choice(per, len(per)).mean() for _ in range(1000)]
    hits = []
    for _, g in A.groupby("day"):
        g = g.to_dict("records")
        hits += [(a[col] > b[col]) == (a["logv"] > b["logv"]) for i, a in enumerate(g) for b in g[i+1:] if abs(a["fixed"]-b["fixed"]) < 0.15 and a["logv"] != b["logv"] and a[col] != b[col]]
    res[col] = {"corr_resid": round(float(per.mean()), 3), "ci95": [round(float(np.percentile(bs, 2.5)), 3), round(float(np.percentile(bs, 97.5)), 3)], "matched_acc": round(100*float(np.mean(hits)), 1), "pairs": len(hits)}
json.dump(res, open("ph_predict/results/simlift.json", "w"), indent=1); print(json.dumps(res, indent=1))
