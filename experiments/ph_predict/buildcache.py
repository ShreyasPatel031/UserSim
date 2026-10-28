"""Cached features.build() + LLM columns (~50 s to rebuild); reused until any input in data/ changes."""
import glob, os, pickle
import features as F, run as RN


def build_cached():
    """F.build() takes ~50 s; reuse it until any input file in data/ (top level) changes."""
    stamp = max(os.path.getmtime(p) for p in glob.glob("data/*.json*") + glob.glob("data/days/*.json") + glob.glob("data/llm_*/*.json")
                + ["features.py", "run.py"])
    path = "data/build_cache" + ("_gemini" if os.environ.get("LLM_PROVIDER") == "gemini" else "") + ".pkl"
    if os.path.exists(path) and os.path.getmtime(path) > stamp:
        return pickle.load(open(path, "rb"))
    df = RN.load_llm(F.build()); pickle.dump(df, open(path, "wb"))
    return df
