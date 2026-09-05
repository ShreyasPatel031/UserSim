"""Gemini 2.5 Flash (Vertex) helpers for MVP agents.

The single LLM provider for this repo. Every inference call goes through here.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

import httpx

from auth import invalidate_credentials, vertex_credentials
from config import GCP_LOCATION, GCP_PROJECT, MODEL


def gemini_model() -> str:
    return (os.environ.get("MVP_LLM_MODEL") or MODEL or "gemini-2.5-flash").strip()


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
        contents.append(
            {"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]}
        )
    system = {"parts": system_parts} if system_parts else None
    return contents, system


def _extract_text(data: dict[str, Any]) -> str:
    for cand in data.get("candidates") or []:
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        if text:
            return text
    raise RuntimeError(f"Gemini returned no text: {json.dumps(data)[:400]}")


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

    url = _endpoint(model)
    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(max_retries):
            creds = await asyncio.to_thread(vertex_credentials)
            headers = {
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json",
            }
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 401:
                invalidate_credentials()
                if attempt < max_retries - 1:
                    continue
            if resp.status_code in (429, 500, 503) and attempt < max_retries - 1:
                try:
                    delay = float(resp.headers.get("retry-after", ""))
                except ValueError:
                    delay = min(60.0, 5.0 * (2**attempt))
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            return _extract_text(resp.json())
    raise RuntimeError("Gemini request failed after retries")


def extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("Model did not return JSON")
    return json.loads(match.group(0))
