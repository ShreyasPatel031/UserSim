"""One function for every simulated-person model call (SIM-RERANK-1 Stage B), so the harness can swap providers.
SIM_MODEL = gemini-2.5-flash (default, PH ops' llm.gemini_call: Vertex, temperature 0). Other values raise until an adapter is added."""
import os, sys
SP = os.environ.get("SIM_SP", "/tmp/claude-0/-home-user-UserSim/d06a24f8-55f2-52b0-9f28-1e7e4ec267d8/scratchpad")
MODEL = os.environ.get("SIM_MODEL", "gemini-2.5-flash")
sys.path.insert(0, os.path.join(SP, "phops", "experiments", "ph_predict")); import llm  # noqa: E402
def call(prompt, max_tokens=400):
    if MODEL == "gemini-2.5-flash": return llm.gemini_call(prompt, max_tokens)
    raise NotImplementedError(f"no adapter for {MODEL}")
def usd():
    return round(llm.USAGE["in"] / 1e6 * 0.30 + llm.USAGE["out"] / 1e6 * 2.50, 4)
