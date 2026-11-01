"""Control: the single LLM judgement (LLM_PROVIDER, Gemini by default) of the pitch already in the model (llm_ inputs), as a separate score."""
import os, sys
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ph_predict"))

NAME = "ai_pitch_score"
NOTES = "existing single-LLM pitch/site/brand scores; the bar persona reactions must clear"


def scores():
    from buildcache import build_cached
    df = build_cached()
    cols = [c for c in df.columns if c.startswith("llm_") and df[c].dtype.kind in "fi"]
    out = df[["id"]].copy(); out["ai_pitch"] = df[cols].rank(pct=True).mean(1)
    return out
