"""Arm-3 rebuild (E5's A+B+C feature table on top of the arm-2 inputs), month-forward Apr-Nov 2026, with per-launch contributions by input
group (LightGBM pred_contrib, seed-averaged). Also arm 2 on the same folds. Inputs are arm 2's (TW.prep, dated before 00:05) plus the A block
(same-day line-up), B block (nearest past launches) and C block (team's earlier launches, days <= d-2), all knowable before 00:05."""
import json, sys, numpy as np, pandas as pd, lightgbm as lgb
import training_window as TW
SP = sys.argv[1]; OUT = f"{SP}/mna/out"; SEEDS = 3
X = pd.read_parquet(f"{SP}/rb/X_full.parquet"); X["id"] = X.id.astype(str); X = X.sort_values(["day", "id"]).drop_duplicates("id").reset_index(drop=True)
T = pd.read_parquet(f"{SP}/rb/arm3_feature_table.parquet"); T["id"] = T.id.astype(str); T = T.drop_duplicates("id", keep="last")
A3 = [c for c in T.columns if c.startswith("A_")] + [c for c in T.columns if c.startswith("B_")] + [c for c in T.columns if c.startswith("C_") and c.endswith("__strong")]
X = X.merge(T[["id"] + A3], on="id", how="left"); X["m"] = X.day.str[:7]; rows = []
for m in sorted(X.m.unique()):
    if m < "2026-04": continue
    tr, te, cols = TW.prep(X[X.m < m], X[X.m == m]); c2 = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]; c3 = c2 + A3
    P = dict(TW.P0, n_jobs=8); M2 = [lgb.LGBMRegressor(random_state=s, **P).fit(tr[c2], tr.logv) for s in range(SEEDS)]; M3 = [lgb.LGBMRegressor(random_state=s, **P).fit(tr[c3], tr.logv) for s in range(SEEDS)]
    p2 = np.mean([q.predict(te[c2]) for q in M2], 0); C = np.mean([q.predict(te[c3], pred_contrib=True) for q in M3], 0)
    out = pd.DataFrame(C[:, :-1], columns=["c_" + c for c in c3]); out["c_bias"] = C[:, -1]; out["pred3"] = C.sum(1); out["pred2"] = p2
    for c in ["id", "day", "dailyRank", "votes", "hist_hunter_n", "hist_hunter_top5", "ph_n_makers", "ph_day_n_launches", "llm_pitch"]: out[c] = te[c].values
    rows.append(out); print(m, len(te), flush=True)
R = pd.concat(rows); R.to_parquet(f"{OUT}/arm3_oos_contrib.parquet"); json.dump({"a3_cols": A3, "c3_cols": c3}, open(f"{OUT}/cols.json", "w"))
