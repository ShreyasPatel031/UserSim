"""Control: the single Claude judgement of the pitch already in the model (llm_ inputs), as a separate score."""
import os, pickle
import pandas as pd

NAME = "ai_pitch_score"
NOTES = "existing single-LLM pitch/site/brand scores; the bar persona reactions must clear"


def scores():
    df = pickle.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "ph_predict", "data", "build_cache.pkl"), "rb"))
    cols = [c for c in df.columns if c.startswith("llm_") and df[c].dtype.kind in "fi"]
    out = df[["id"]].copy(); out["ai_pitch"] = df[cols].rank(pct=True).mean(1)
    return out
