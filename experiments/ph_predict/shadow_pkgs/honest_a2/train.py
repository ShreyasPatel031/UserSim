"""Train shadow_honest_a2: the live launch model's prediction as a Poisson offset, corrected by day terms (as daycal), A1
(team launch history) and A2 (team's comments on other launches in the 7 / 14 days before). Trained on every backtest
day (Apr-Oct) with the honest live-set prediction as the offset. Writes model_s0..s4.txt, meta.json, team_history.jsonl
(the 2024-2025 crawl, for live A1; bucket / VM only, never commit: it holds usernames).
usage (from ph_predict): SIMLAB_DATA=data_v2 python shadow_pkgs/honest_a2/train.py <out_dir> <honest_live_preds.parquet>
       <a1_features.parquet> <a2_features.parquet> <ph_team_history.jsonl>"""
import json, os, shutil, sys
import numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import userbase_eval as UE

A1 = ["a1_mean_rel", "a1_top5", "a1_n", "a1_first"]
A2 = ["a2_act7", "a2_act14", "a2_launches14", "a2_active_members14", "a2_days_since"]


def main(out, preds, a1, a2, hist):
    os.makedirs(out, exist_ok=True)
    os.environ["HONEST_PREDS"] = preds; os.environ["HONEST_COL"] = "honest - live set"
    H = UE.honest()
    for p, cols in ((a1, A1), (a2, A2)):
        X = pd.read_parquet(p); X["id"] = X.id.astype(str); H = H.merge(X[["id"] + cols], on="id", how="left")
    A = UE.day_terms(H); A = A[A.day >= "2026-04-01"]
    cols = UE.DAY_COLS + A1 + A2
    for s in range(5):
        lgb.train({"objective": "poisson", "learning_rate": 0.03, "num_leaves": 7, "min_data_in_leaf": 100, "bagging_fraction": 0.8,
                   "bagging_freq": 1, "seed": s, "verbose": -1, "num_threads": 8},
                  lgb.Dataset(A[cols], A.y, init_score=np.log(A.mu0)), num_boost_round=200).save_model(f"{out}/model_s{s}.txt")
    D = A.groupby("day").agg(real=("y", "sum"), lm=("mu0", "sum"))
    json.dump({"name": "honest_a2", "features": cols, "models": [f"model_s{s}.txt" for s in range(5)], "trained_on": [A.day.min(), A.day.max()],
               "launches": len(A), "reference": "honest - live set (62.7 / 70.4 / 76.6 daily, May-Oct)",
               "day_real": {d: float(v) for d, v in D.real.items()}, "day_lm": {d: float(v) for d, v in D.lm.items()}}, open(f"{out}/meta.json", "w"), indent=1)
    shutil.copy(hist, f"{out}/team_history.jsonl")
    print("trained on", len(A), "launches", A.day.min(), A.day.max())


if __name__ == "__main__":
    main(*sys.argv[1:6])
