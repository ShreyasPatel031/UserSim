"""Crowd v0: persona reactions x who sees it (base visibility, higher for people who follow the poster/makers)."""
import os
import pandas as pd
from simlab import crowd

NAME = "persona_crowd"
UNDATED = ["follow lists read today", "persona cards use current segment labels and LinkedIn headlines"]


def scores():
    P = pd.read_parquet(os.path.join(os.path.dirname(__file__), "..", "cache", "persona_person_scores.parquet"))
    out = None
    for bs, fs, b, tag in ((0.3, 0.9, 0, "crowd"), (0.3, 0.9, 1.0, "crowd_herd"), (0.1, 0.9, 0, "crowd_followheavy")):
        V, share = crowd.expected_votes(P, bs, fs, b)
        V = V.rename(columns={"crowd": tag})
        out = V if out is None else out.merge(V, on="id")
    return out
