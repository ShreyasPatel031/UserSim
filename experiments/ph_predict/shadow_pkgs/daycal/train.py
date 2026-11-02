"""Train the day-calibrated weekly forecast (ph_predict/daycal.py's model) on every finished day of the backtest and
write the package for the pipeline's shadow slot: model_s0..s4.txt, meta.json, lm_days.json (each backtest day's
launch-model total, for the trailing input until live forecasts cover it).
usage (from ph_predict): SIMLAB_DATA=data_v2 python shadow_pkgs/daycal/train.py <out_dir>"""
import json, os, sys
import numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import daycal as DC

out = sys.argv[1]; os.makedirs(out, exist_ok=True)
C = pd.read_parquet("results/ctrl_preds.parquet"); C["id"] = C.id.astype(str); C = C.drop_duplicates("id")
A = C[["id", "day", "logv", "all"]].copy()
A["mu0"] = np.expm1(A["all"]).clip(lower=0.5); A["y"] = np.expm1(A.logv).clip(lower=0)
D = A.groupby("day").agg(day_n=("id", "size"), day_lm_sum=("mu0", "sum"), real=("y", "sum")).sort_index()
D["day_wd"] = pd.to_datetime(D.index).weekday
D["trail_real7"] = D.real.shift(2).rolling(7, min_periods=3).mean()
D["trail_lm7"] = D.day_lm_sum.shift(2).rolling(7, min_periods=3).mean()
A = A.merge(D[DC.COLS], left_on="day", right_index=True)
A = A[A.day >= "2026-04-01"]
for s in range(5):
    lgb.train({"objective": "poisson", "learning_rate": 0.03, "num_leaves": 7, "min_data_in_leaf": 100, "bagging_fraction": 0.8, "bagging_freq": 1,
               "seed": s, "verbose": -1, "num_threads": 8}, lgb.Dataset(A[DC.COLS], A.y, init_score=np.log(A.mu0)), num_boost_round=200).save_model(f"{out}/model_s{s}.txt")
json.dump({"name": "daycal", "features": DC.COLS, "models": [f"model_s{s}.txt" for s in range(5)], "trained_on": [A.day.min(), A.day.max()],
           "launches": len(A), "evaluation": "simlab/reports/daycal.json (weekly top 3 +4.0 [0.0, +9.3], 25 weeks)"}, open(f"{out}/meta.json", "w"), indent=1)
json.dump({d: float(v) for d, v in D.day_lm_sum.items()}, open(f"{out}/lm_days.json", "w"))
print("trained on", len(A), "launches", A.day.min(), A.day.max())
