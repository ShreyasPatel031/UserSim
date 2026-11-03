"""Joint test of the small honest pre-launch inputs on top of the live honest set + day calibration: A1 (team launch
history), A2 (team's comments on other launches in the days before, comments only) and C1 (stars / downloads before
launch), one model, paired vs the control (userbase_eval). Also writes the combined feature file for the shock model.
usage: SIMLAB_DATA=data_v2 HONEST_PREDS=... HONEST_COL="honest - live set" python joint_honest.py <a1_features.parquet>
       <a2_features.parquet> <c1_features.parquet> -> results/joint_honest.json, /home/agent/joint_features.parquet"""
import os, sys
import pandas as pd
import userbase_eval as UE

KEEP = {"a1": ["a1_mean_rel", "a1_top5", "a1_n", "a1_first"], "a2": ["a2_act7", "a2_act14", "a2_launches14", "a2_active_members14", "a2_days_since"],
        "c1": ["c1_stars", "c1_stars_30", "c1_dl_30"]}


def main(a1, a2, c1):
    F = None
    for path, block in ((a1, "a1"), (a2, "a2"), (c1, "c1")):
        X = pd.read_parquet(path); X["id"] = X.id.astype(str)
        cols = [c for c in KEEP[block] if c in X]
        X = X[["id"] + cols]
        F = X if F is None else F.merge(X, on="id", how="outer")
    cols = [c for c in F if c != "id"]
    F.to_parquet(os.environ.get("FEATS_OUT", "/home/agent/joint_features.parquet"))
    return UE.evaluate(F, "joint", cols, os.environ.get("OUT", "results/joint_honest.json"))


if __name__ == "__main__":
    main(*sys.argv[1:4])
