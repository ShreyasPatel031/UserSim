"""Launch level of the choice model: expected votes from recently active sampled people,
P(upvote) from popularity + relationships + taste (simlab/choice.py)."""
import os
import pandas as pd

NAME = "choice_votes"
UNDATED = ["follow lists read today"]


def scores():
    return pd.read_parquet(os.path.join(os.path.dirname(__file__), "..", "cache", "choice_votes.parquet"))
