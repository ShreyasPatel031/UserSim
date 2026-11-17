"""Month-forward out-of-sample arm-2 predictions for every launch 2025-04..2026-11 (train = all days before the month, 5 seeds)."""
import sys, numpy as np, pandas as pd, lightgbm as lgb
import training_window as TW
SP = sys.argv[1]; X = pd.read_parquet(f"{SP}/rb/X_full.parquet"); X["id"] = X.id.astype(str); X = X.sort_values(["day", "id"]).reset_index(drop=True)
X["m"] = X.day.str[:7]; out = []
for m in sorted(X.m.unique()):
    if m < "2026-09": continue
    tr, te, cols = TW.prep(X[X.m < m], X[X.m == m]); cc = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]
    p = np.mean([lgb.LGBMRegressor(random_state=s, **dict(TW.P0, n_jobs=6)).fit(tr[cc], tr.logv).predict(te[cc]) for s in range(5)], axis=0)
    out.append(pd.DataFrame({"id": te.id.values, "pred": p})); print(m, len(te), flush=True)
pd.concat(out).to_parquet(f"{SP}/fcv/arm2_oos.parquet")
