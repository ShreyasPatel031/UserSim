"""Persona reactions (50 real Product Hunt people per launch, 40 taste-matched + 10 random, Gemini Flash, SSR score)."""
import os
import pandas as pd

NAME = "persona_appeal"
UNDATED = ["persona cards use current segment labels and LinkedIn headlines"]
NOTES = "Sep-Oct launches; per-launch mean SSR score, share >= 3.5, matched-only and random-only means"


def scores():
    return pd.read_parquet(os.path.join(os.path.dirname(__file__), "..", "cache", "persona_scores.parquet")).drop(columns=["persona_n"])
