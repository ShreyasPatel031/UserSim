"""Cheap depth of the persona engine: the per-person choice model (vote_sim2: taste, past backing, reciprocity,
follows) summed over the 19k sampled people. Trained on Mar-Aug, scored Sep-Oct."""
import os
import numpy as np, pandas as pd

NAME = "cheap_scorer"
UNDATED = ["follow lists read today", "segment-based person traits"]


def scores():
    ph = os.path.join(os.path.dirname(__file__), "..", "..", "ph_predict", "data")
    Z = np.load(os.path.join(ph, "vote_sim_scores_2026-09-01.npz"), allow_pickle=True)  # our own file
    L = pd.read_parquet(os.path.join(os.path.dirname(__file__), "..", "data", "items.parquet"))
    lid = Z["launch_id"]  # launch id per row (saved by vote_sim2 since the stable-order fix)
    out = {}
    for s in ("s0", "s1"):
        g = Z["person"].astype(np.int64) * 1000 + Z["dn"].astype(np.int64)
        df = pd.DataFrame({"g": g, "launch": lid, "s": Z[s], "w": Z["act"] * Z["per"]})
        df["e"] = np.exp(df.s - df.groupby("g").s.transform("max")); df["share"] = df.e / df.groupby("g").e.transform("sum")
        out[f"cheap_{s}"] = (df.share * df.w).groupby(df.launch).sum()
    R = pd.DataFrame(out); R.index.name = "id"
    return R.reset_index()[["id", "cheap_s0", "cheap_s1"]]
