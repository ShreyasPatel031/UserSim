"""Gemini 2.5 Flash (Vertex) helpers for MVP agents.

The single LLM provider for this repo. Every inference call goes through here.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import os
import random
import re
import time
from typing import Any, Iterator

import httpx

from auth import cached_vertex_credentials, invalidate_credentials, vertex_credentials
from config import GCP_LOCATION, GCP_PROJECT, MODEL


def gemini_model() -> str:
    return (os.environ.get("MVP_LLM_MODEL") or MODEL or "gemini-2.5-flash-lite").strip()


def gemini_project() -> str:
    project = (
        os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("GCP_PROJECT")
        or GCP_PROJECT
        or ""
    ).strip()
    if not project:
        raise RuntimeError("No GCP project set (GOOGLE_CLOUD_PROJECT)")
    return project


def gemini_location() -> str:
    return (os.environ.get("VERTEX_LOCATION") or GCP_LOCATION or "us-central1").strip()


def _endpoint(model: str) -> str:
    loc = gemini_location()
    host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
    return (
        f"https://{host}/v1/projects/{gemini_project()}"
        f"/locations/{loc}/publishers/google/models/{model}:generateContent"
    )


def _to_vertex(messages: list[dict[str, str]]) -> tuple[list[dict], dict | None]:
    """OpenAI-style messages -> Vertex contents + systemInstruction."""
    contents: list[dict] = []
    system_parts: list[dict] = []
    for msg in messages:
        role = (msg.get("role") or "user").strip()
        text = msg.get("content") or ""
        if not text:
            continue
        if role == "system":
            system_parts.append({"text": text})
            continue
        parts: list[dict] = [{"text": text}]
        image = msg.get("image_b64") or ""
        if image:
            # Optional screenshot for a vision check. Base64 JPEG or PNG bytes.
            parts.append(
                {"inline_data": {"mime_type": msg.get("image_mime") or "image/jpeg", "data": image}}
            )
        contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
    system = {"parts": system_parts} if system_parts else None
    return contents, system


def _extract_text(data: dict[str, Any]) -> str:
    for cand in data.get("candidates") or []:
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        if text:
            return text
    raise RuntimeError(f"Gemini returned no text: {json.dumps(data)[:400]}")


THROTTLES: dict[str, int] = {}


def _note_throttle(model: str, status: int, took_s: float) -> None:
    key = f"{model}:{status}"
    THROTTLES[key] = THROTTLES.get(key, 0) + 1
    n = THROTTLES[key]
    if n <= 5 or n % 25 == 0:
        print(f"[gemini] {status} from {model} after {took_s:.1f}s (#{n})", flush=True)


# Vertex list price, USD per 1M tokens (text, <=200k context). Longest prefix wins.
PRICES_PER_M: dict[str, tuple[float, float]] = {
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.30, 2.50),  # pragma: allowlist secret
    "gemini-2.5-flash-lite": (0.10, 0.40),  # pragma: allowlist secret
    "gemini-2.0-flash": (0.15, 0.60),
    "gemini-2.0-flash-lite": (0.075, 0.30),
}

_USAGE_SINK: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "gemini_usage_sink", default=None
)


@contextlib.contextmanager
def track_usage() -> Iterator[list[dict[str, Any]]]:
    """Collect one usage row per gemini_chat call made inside the block (and tasks it starts)."""
    rows: list[dict[str, Any]] = []
    token = _USAGE_SINK.set(rows)
    try:
        yield rows
    finally:
        _USAGE_SINK.reset(token)


def token_usage(data: dict[str, Any]) -> tuple[int, int]:
    """(input, output) tokens from a generateContent reply. Output counts thinking tokens."""
    meta = data.get("usageMetadata") or {}
    try:
        tokens_in = int(meta.get("promptTokenCount") or 0)
        tokens_out = int(meta.get("candidatesTokenCount") or 0) + int(meta.get("thoughtsTokenCount") or 0)
    except (TypeError, ValueError):
        return 0, 0
    return tokens_in, tokens_out


def estimate_cost_usd(rows: list[dict[str, Any]]) -> float | None:
    """List-price cost of usage rows; None when a row's model has no known price."""
    total = 0.0
    for row in rows:
        model = str(row.get("model") or "")
        key = max((k for k in PRICES_PER_M if model.startswith(k)), key=len, default=None)
        if key is None:
            return None
        price_in, price_out = PRICES_PER_M[key]
        total += (row.get("input_tokens") or 0) * price_in / 1e6 + (row.get("output_tokens") or 0) * price_out / 1e6
    return round(total, 6)


def _note_usage(model: str, data: dict[str, Any], took_s: float) -> None:
    tokens_in, tokens_out = token_usage(data)
    sink = _USAGE_SINK.get()
    if sink is not None:
        sink.append({"model": model, "input_tokens": tokens_in, "output_tokens": tokens_out, "s": round(took_s, 2)})
    if os.environ.get("MVP_LLM_LOG_TOKENS", "1").strip().lower() not in {"0", "false", "no"}:
        print(f"[gemini] tokens {model} in={tokens_in} out={tokens_out} after {took_s:.1f}s", flush=True)


def retry_sleep_cap() -> float:
    """Longest pause between retries (MVP_LLM_RETRY_MAX_S, default 3s).

    Step calls run under a 4.5-20s timeout; the old 5s/10s back-off alone
    outlived it.
    """
    try:
        return max(0.1, float(os.environ.get("MVP_LLM_RETRY_MAX_S") or 3.0))
    except ValueError:
        return 3.0


def fallback_model(model: str) -> str | None:
    """Model to try after a 429 (separate quota). MVP_LLM_FALLBACK_MODEL; "0" disables."""
    raw = (os.environ.get("MVP_LLM_FALLBACK_MODEL") or "").strip()
    if raw.lower() in {"0", "none", "off"}:
        return None
    if raw:
        return raw if raw != model else None
    if model.endswith("-lite"):
        return model[: -len("-lite")]
    if model.startswith("gemini-2.5-flash"):
        return "gemini-2.5-flash-lite"
    return None


async def gemini_chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.4,
    json_mode: bool = True,
    max_retries: int = 5,
) -> str:
    """Call Gemini on Vertex. Returns the raw text of the first candidate."""
    model = model or gemini_model()
    contents, system = _to_vertex(messages)

    generation: dict[str, Any] = {"temperature": temperature}
    if json_mode:
        generation["responseMimeType"] = "application/json"
    # 2.5 Flash thinks by default; signup/study prompts do not need it and it
    # doubles latency and cost.
    generation["thinkingConfig"] = {"thinkingBudget": 0}

    payload: dict[str, Any] = {"contents": contents, "generationConfig": generation}
    if system:
        payload["systemInstruction"] = system

    fallback = fallback_model(model)
    # Step calls (max_retries <= 2) run under a short timeout: retry fast.
    # Report/judge calls keep the long back-off.
    quick = max_retries <= 2
    async with httpx.AsyncClient(timeout=120.0) as client:
        use = model
        for attempt in range(max_retries):
            url = _endpoint(use)
            creds = cached_vertex_credentials() or await asyncio.to_thread(vertex_credentials)
            headers = {
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json",
            }
            t0 = time.perf_counter()
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 401:
                invalidate_credentials()
                if attempt < max_retries - 1:
                    continue
            if resp.status_code in (429, 500, 503) and attempt < max_retries - 1:
                _note_throttle(use, resp.status_code, time.perf_counter() - t0)
                try:
                    delay = float(resp.headers.get("retry-after", ""))
                except ValueError:
                    delay = 0.5 * (2**attempt) + random.uniform(0, 0.5) if quick else 5.0 * (2**attempt)
                await asyncio.sleep(min(delay, retry_sleep_cap() if quick else 60.0))
                # A 429 is per-model quota: the next try goes to the fallback model.
                if resp.status_code == 429 and fallback:
                    use = fallback
                continue
            resp.raise_for_status()
            data = resp.json()
            _note_usage(use, data, time.perf_counter() - t0)
            return _extract_text(data)
    raise RuntimeError("Gemini request failed after retries")


def extract_json(text: str) -> dict:
    """Parse the first JSON object. Extra objects after it are ignored."""
    raw = text or ""
    start = raw.find("{")
    if start < 0:
        raise ValueError("Model did not return JSON")
    try:
        data, _end = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Model JSON was not an object")
    return data
