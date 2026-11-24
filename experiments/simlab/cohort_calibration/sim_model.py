"""One function for every simulated-person model call (SIM-RERANK-1 Stage B), so the harness can swap providers.
SIM_MODEL = gemini-2.5-flash (default): Vertex generateContent, temperature 0, JSON output, no thinking budget, same request as PH ops'
llm.gemini_call (self-contained here so the nightly job runs in a fresh session). Other values raise until an adapter is added."""
import json, os, subprocess, threading, time, urllib.request
MODEL = os.environ.get("SIM_MODEL", "gemini-2.5-flash")
_URL = ("https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/models/{m}:generateContent")
USAGE = {"in": 0, "out": 0}; _tok = {"t": "", "at": 0}; _lk = threading.Lock()
def _token():
    with _lk:
        if time.time() - _tok["at"] > 1800:
            _tok["t"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip(); _tok["at"] = time.time()
        return _tok["t"]
def _gemini(prompt, max_tokens, model):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens, "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}}
    for i in range(6):
        try:
            req = urllib.request.Request(_URL.format(m=model), json.dumps(body).encode(), {"Authorization": "Bearer " + _token(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                j = json.load(r); u = j.get("usageMetadata", {})
                with _lk: USAGE["in"] += u.get("promptTokenCount", 0); USAGE["out"] += u.get("candidatesTokenCount", 0)
                return "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        except Exception as e:  # noqa: BLE001
            if "403" in str(e) or "PERMISSION" in str(e).upper(): raise
            time.sleep(5 * (i + 1))
    return ""
def call(prompt, max_tokens=400):
    if MODEL.startswith("gemini-"): return _gemini(prompt, max_tokens, MODEL)
    raise NotImplementedError(f"no adapter for {MODEL}")
def usd():
    return round(USAGE["in"] / 1e6 * 0.30 + USAGE["out"] / 1e6 * 2.50, 4)
