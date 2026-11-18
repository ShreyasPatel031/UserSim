"""Arm-2 explain dump for E5 (E5 23:34Z Nov 13; counts only, no names or handles). Re-runs arm 2 exactly as the 214-day backtest ('both'
of history_retrain.py DECOMP=1 ARM=2: month-forward, 5 seeds, TW.P0) and writes to gs://.../tmp/ph_ops/arm2_explain/:
  X.parquet       id, day, mon, the model inputs as fed to the booster, dailyRank, both (seed-mean prediction)
  shap.parquet    id, day, one column per input = LightGBM pred_contrib averaged over the 5 seeds, plus bias (row sum = both)
  models/<mon>_s<seed>.txt   booster text files (save_model)
  cols.json       the input list per month (same 40 every month unless prep changes it)
  rescore.py      re-score a modified X with the boosters
usage (VM, from ~/w/experiments/ph_predict): PYTHONPATH=~/w/mk:.:~/w/h25 H25_SRC=~/w/ph_history/2025 ARM=2 python3 ~/w/h25/arm2_explain.py <out dir>"""
import json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
import history_retrain as HR, training_window as TW
OUT = sys.argv[1]; os.makedirs(f"{OUT}/models", exist_ok=True)
df, _ = HR.build(os.environ.get("H25_SRC", os.path.expanduser("~/w/ph_history/2025"))); old = df.day < "2026-01-01"
Xs, Ss, CJ = [], [], {}
for m in ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]:
    tr, te, cols = TW.prep(df[df.mon < m], df[(df.mon == m) & ~old])
    cols = [c for c in cols if c not in TW.ID_COLS and c not in ("llm_site", "ph_month")]; CJ[m] = cols
    P, C = [], []
    for s in range(5):
        b = lgb.LGBMRegressor(random_state=s, **TW.P0).fit(tr[cols], tr.logv)
        b.booster_.save_model(f"{OUT}/models/{m}_s{s}.txt")
        P.append(b.predict(te[cols])); C.append(b.predict(te[cols], pred_contrib=True))
    X = te[["id", "day", "mon"] + cols + ["dailyRank"]].copy(); X["id"] = X.id.astype(str); X["both"] = np.mean(P, 0)
    S = pd.DataFrame(np.mean(C, 0), columns=cols + ["bias"]); S.insert(0, "day", te.day.values); S.insert(0, "id", te.id.astype(str).values)
    Xs.append(X); Ss.append(S); print(json.dumps({"month": m, "rows": len(X), "inputs": len(cols)}), flush=True)
X = pd.concat(Xs, ignore_index=True); S = pd.concat(Ss, ignore_index=True)
X.to_parquet(f"{OUT}/X.parquet"); S.to_parquet(f"{OUT}/shap.parquet"); json.dump(CJ, open(f"{OUT}/cols.json", "w"), indent=1)
chk = float(np.abs(S.drop(columns=["id", "day"]).sum(1).values - X.both.values).max())
A = pd.read_parquet("results/history_retrain_decomp_preds_arm2.parquet") if os.path.exists("results/history_retrain_decomp_preds_arm2.parquet") else None
open(f"{OUT}/rescore.py", "w").write('''"""usage: from rescore import rescore; pred = rescore(X_modified, models_dir, cols_json)  # seed-mean, per month"""
import json, numpy as np, lightgbm as lgb
def rescore(X, md, cj):
    C = json.load(open(cj)); out = np.full(len(X), np.nan)
    for m, cols in C.items():
        k = (X["mon"] == m).values
        if k.any():
            out[k] = np.mean([lgb.Booster(model_file=f"{md}/{m}_s{s}.txt").predict(X.loc[k, cols]) for s in range(5)], 0)
    return out
''')
print(json.dumps({"rows": len(X), "days": int(X.day.nunique()), "max |sum(shap) - both|": round(chk, 6)}))
