"""Gemini on Vertex only (no Claude, no other providers). Cached JSON calls with measured token cost.

Cost = Vertex list prices x the token counts Vertex returns (prompt + output + thinking). meter() totals by stage;
flush_spend() writes the totals to the warehouse spend table."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections import defaultdict
from pathlib import Path

import store  # noqa: F401  (puts src/ on sys.path)

FLASH, LITE = "gemini-2.5-flash", "gemini-2.5-flash-lite"
PRICES = {FLASH: (0.30, 2.50), LITE: (0.10, 0.40)}   # $ per 1M tokens in / out (Vertex list, <=200k context)
CACHE = Path(os.environ.get("HN_SIM_CACHE", Path(__file__).resolve().parent / "out" / "calls"))
CAP = float(os.environ.get("HN_SIM_CAP_USD", "5"))
_lock = threading.Lock()
_meter: dict[str, list[float]] = defaultdict(lambda: [0, 0, 0, 0.0])   # stage -> calls, in, out, usd
_client = None


def client():
    global _client
    if _client is None:
        import model as repo_model
        _client = repo_model._client()
    return _client


def spent() -> float:
    return sum(v[3] for v in _meter.values())


def parse_json(t: str):
    t = (t or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1)
    for cand in (t, t[t.find("{"):t.rfind("}") + 1]):
        try:
            return json.loads(cand)
        except ValueError:
            continue
    return None


def call(stage: str, prompt: str, *, system: str = "", model: str = FLASH, temperature: float = 0.0, seed: int = 0,
         thinking: int = 0, images: list[bytes] | None = None, max_tokens: int = 4096, cache: bool = True) -> dict:
    """One JSON call. Returns the parsed JSON (dict) or {} on failure; '_usd' holds this call's cost (0 if cached)."""
    from google.genai import types
    key = hashlib.sha256(json.dumps([model, system, prompt, temperature, seed, thinking, max_tokens,
                                     [hashlib.sha256(i).hexdigest() for i in images or []]]).encode()).hexdigest()
    path = CACHE / f"{key}.json"
    if cache and path.exists():
        try:
            return json.loads(path.read_text())["json"]
        except (ValueError, KeyError):
            pass
    if spent() > CAP:
        raise RuntimeError(f"hn_sim spend cap ${CAP} reached")
    parts = [types.Part.from_bytes(data=b, mime_type="image/jpeg") for b in images or []] + [types.Part.from_text(text=prompt)]
    cfg = types.GenerateContentConfig(system_instruction=system or None, temperature=temperature, seed=seed,
                                      max_output_tokens=max_tokens, response_mime_type="application/json",
                                      thinking_config=types.ThinkingConfig(thinking_budget=thinking))
    err = None
    for i in range(5):
        try:
            r = client().models.generate_content(model=model, contents=[types.Content(role="user", parts=parts)],
                                                 config=cfg)
            break
        except Exception as exc:  # noqa: BLE001
            err = exc
            time.sleep(2 ** (i + 1))
    else:
        raise RuntimeError(f"{stage}: {err}")
    u = r.usage_metadata
    inp, out = u.prompt_token_count or 0, (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
    pin, pout = PRICES[model]
    usd = inp / 1e6 * pin + out / 1e6 * pout
    with _lock:
        m = _meter[stage]
        m[0] += 1; m[1] += inp; m[2] += out; m[3] += usd  # noqa: E702
    j = parse_json(r.text or "")
    j = j if isinstance(j, (dict, list)) else {}
    if isinstance(j, list):
        j = {"items": j}
    j["_usd"] = usd
    if cache:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"stage": stage, "model": model, "in": inp, "out": out, "usd": usd, "json": j}))
        os.replace(tmp, path)
    return j


def meter() -> dict:
    return {k: {"calls": v[0], "in": v[1], "out": v[2], "usd": round(v[3], 4)} for k, v in _meter.items()}


def flush_spend(step: str, note: str = "") -> float:
    """Log this process's measured model spend (since the last flush) to the warehouse, then reset."""
    usd = spent()
    if usd > 0:
        store.spend(step, usd, f"{note} {json.dumps(meter())}".strip(), provider="gcp")
    _meter.clear()
    return usd
