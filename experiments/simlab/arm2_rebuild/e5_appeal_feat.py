"""Does the persona panel's "appeal" predict where a launch lands? (PREREG_persona_appeal.md; orchestrator 01:38Z Nov 15). Same harness as
e5_ring_feat / e5_makers0: 2026-04..10 month-forward, deployed columns, TW.P0, 5 seeds, rows sorted by (day, id), train from 2025-01-01.
Features: appeal_high, appeal_mean (persona_appeal.py; NaN where no panel; present for 2026-01 onward). Columns: arm2, fix (arm2 + appeal).
Also: within-day Spearman of appeal_mean with arm2's residual (logv - arm2 prediction), averaged over days with >= 5 paneled launches,
day bootstrap 2000 -> <out>.spearman.json.
    usage: APPEAL=<appeal jsonl> python e5_appeal_feat.py <out parquet>"""
import json, os, sys, time
os.environ.setdefault("LGB_THREADS", "4")
import numpy as np, pandas as pd, lightgbm as lgb
from scipy.stats import spearmanr
import history_retrain as HR, training_window as TW
t0 = time.time(); OUT = sys.argv[1]; SEEDS = range(5); rng = np.random.default_rng(0)
df, _ = HR.build(os.environ["H25_SRC"]); X = df.reset_index(drop=True); X["id"] = X.id.astype(str); X = X.sort_values(["day", "id"]).reset_index(drop=True)
A = pd.DataFrame([json.loads(l) for l in open(os.environ["APPEAL"])]); A["id"] = A.id.astype(str); A = A.drop_duplicates("id", keep="last").set_index("id")
FE = ["appeal_high", "appeal_mean"]
P = dict(TW.P0, n_jobs=int(os.environ["LGB_THREADS"]))
def fit(tr, te, cols): return np.array([lgb.LGBMRegressor(random_state=s, **P).fit(tr[cols], tr.logv).predict(te[cols]) for s in SEEDS]).mean(0)
rows = []
for m in [f"2026-{k:02d}" for k in range(4, 11)]:
    te0 = X[X.mon == m]; tr0 = X[(X.mon < m) & (X.day >= "2025-01-01")]
    tr, te, cols = TW.prep(tr0, te0); base = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
    tr, te = tr.sort_values(["day", "id"]).copy(), te.sort_values(["day", "id"]).copy()
    for c in FE: tr[c] = tr.id.map(A[c]).astype(float).values; te[c] = te.id.map(A[c]).astype(float).values
    o = te[["id", "day", "dailyRank"]].copy(); o["year"] = "2026"; o["arm2"] = fit(tr, te, base); o["fix"] = fit(tr, te, base + FE)
    o["logv"] = te.logv.values
    for c in FE: o[c] = te[c].values
    rows.append(o); print(json.dumps({"month": m, "n_test": len(te), "test with appeal": int(te.appeal_mean.notna().sum()),
                                      "train with appeal": int(tr.appeal_mean.notna().sum()), "s": round(time.time() - t0)}), flush=True)
R = pd.concat(rows).assign(zero_makers=False); R.to_parquet(OUT)
R["resid"] = R.logv - R.arm2; R["dstr"] = R.day.astype(str).str[:10]
rho = {}
for d, g in R[R.appeal_mean.notna()].groupby("dstr"):
    if len(g) >= 5 and g.appeal_mean.nunique() > 1:
        rho[d] = (spearmanr(g.appeal_mean, g.resid).statistic, spearmanr(g.appeal_mean, g.logv).statistic, spearmanr(g.appeal_high, g.resid).statistic)
V = np.array(list(rho.values()), float)
def bs(col):
    v = V[:, col]; v = v[~np.isnan(v)]; b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
    return [round(float(v.mean()), 3), round(float(np.percentile(b, 2.5)), 3), round(float(np.percentile(b, 97.5)), 3), int(len(v))]
S = {"days": len(rho), "launches with appeal (test)": int(R.appeal_mean.notna().sum()), "launches (test)": int(len(R)),
     "spearman appeal_mean vs arm2 residual (mean over days) [95% day bootstrap, n days]": bs(0),
     "spearman appeal_mean vs logv (raw, for scale)": bs(1), "spearman appeal_high vs arm2 residual": bs(2)}
json.dump(S, open(OUT + ".spearman.json", "w"), indent=1); print(json.dumps(S), flush=True); print("done", flush=True)
