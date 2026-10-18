"""Vertex Gemini call for this experiment: the project's endpoint and credentials,
with usage logged and no silent model fallback.

capability.gemini_config.gemini_chat drops usageMetadata and switches to a
different model after a 429. Every forecast cell must use one fixed model, so
this wrapper retries the same model and records exactly what served the call.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "src", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import httpx  # noqa: E402

from auth import cached_vertex_credentials, invalidate_credentials, vertex_credentials  # noqa: E402
from capability.gemini_config import _endpoint, _to_vertex, extract_json  # noqa: E402,F401

# Vertex list prices, USD per 1M tokens (text). Recorded with each call.
PRICES = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}

FORECAST_MODEL = "gemini-2.5-flash"
FORECAST_TEMPERATURE = 0.0


async def call(
    prompt: str,
    *,
    system: str | None = None,
    model: str = FORECAST_MODEL,
    temperature: float = FORECAST_TEMPERATURE,
    max_retries: int = 6,
) -> dict[str, Any]:
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    contents, sys_inst = _to_vertex(messages)
    return await call_contents(contents, sys_inst, model=model, temperature=temperature, max_retries=max_retries)


async def call_contents(
    contents: list[dict],
    sys_inst: dict | None,
    *,
    model: str = FORECAST_MODEL,
    temperature: float = FORECAST_TEMPERATURE,
    max_retries: int = 6,
) -> dict[str, Any]:
    """Same call with prebuilt Vertex contents (used for the image-bearing trace judge)."""
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    if sys_inst:
        payload["systemInstruction"] = sys_inst
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=180.0) as client:
        for attempt in range(max_retries):
            creds = cached_vertex_credentials() or await asyncio.to_thread(vertex_credentials)
            resp = await client.post(
                _endpoint(model),
                headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code == 401 and attempt < max_retries - 1:
                invalidate_credentials()
                continue
            if resp.status_code in (429, 500, 503) and attempt < max_retries - 1:
                await asyncio.sleep(5.0 * (2**attempt))
                continue
            resp.raise_for_status()
            data = resp.json()
            break
    text = ""
    for cand in data.get("candidates") or []:
        text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts") or []).strip()
        if text:
            break
    usage = data.get("usageMetadata") or {}
    inp = int(usage.get("promptTokenCount") or 0)
    out = int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0)
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return {
        "text": text,
        "json": extract_json(text) if text else None,
        "model": model,
        "model_version": data.get("modelVersion"),
        "usage": {
            "input_tokens": inp,
            "output_tokens": out,
            "cost_usd": round(inp / 1e6 * pin + out / 1e6 * pout, 6),
            "latency_seconds": round(time.perf_counter() - t0, 2),
        },
    }


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)
