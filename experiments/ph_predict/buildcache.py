"""Cached features.build() + LLM columns (~50 s to rebuild); reused until an input that build reads changes."""
import glob, os, pickle, tempfile
import features as F, run as RN


def _stamp():
    """Newest mtime over the files F.build() and RN.load_llm() actually read. Other files in data/ (e.g. the *_features.json
    that simlab popscore runs write there) must not count, or each finished run makes every parallel run rebuild the cache."""
    here = os.path.dirname(os.path.abspath(__file__))
    paths = [os.path.join(F.D, n) for n in F.INPUTS]
    paths += glob.glob(os.path.join(F.D, "days", "*.json")) + glob.glob(os.path.join(F.D, "llm_*", "*.json"))
    paths += [os.path.join(here, "features.py"), os.path.join(here, "run.py")]
    return max(os.path.getmtime(p) for p in paths if os.path.exists(p))


def cache_path():
    """The pickle build_cached() reads and writes for the current LLM_PROVIDER (absolute path)."""
    gem = os.environ.get("LLM_PROVIDER", "gemini") == "gemini"
    return os.path.join(F.D, "build_cache" + ("_gemini" if gem else "") + ".pkl")


def build_cached():
    """F.build() takes ~50 s; reuse it until one of its inputs changes. The pickle is written to a temp file and renamed into
    place, so a concurrent reader sees either the old cache or the new one, never a partial file."""
    path = cache_path()
    if os.path.exists(path) and os.path.getmtime(path) > _stamp():
        with open(path, "rb") as f:
            return pickle.load(f)
    df = RN.load_llm(F.build())
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            pickle.dump(df, f)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
    return df
