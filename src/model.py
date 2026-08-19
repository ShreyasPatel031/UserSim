"""Gemini 2.5 Flash next-action predictor (no training)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from auth import vertex_credentials
from config import GCP_LOCATION, GCP_PROJECT, MODEL, PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M

SYSTEM = """You predict the next UI action a real human will take on a website.
You are given a task, the current page as a numbered list of interactive elements, and optionally the person's previous actions.
Pick exactly one element from the list and one action type: CLICK, TYPE, or SELECT.
For TYPE, set value to the text the human would type. For SELECT, set value to the option they would choose. For CLICK, value must be null.
Return JSON only."""


@dataclass
class PredictResult:
    element_index: int | None
    action: str | None
    value: str | None
    raw: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


@dataclass
class TokenMeter:
    prompt_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    errors: int = 0

    def add(self, result: PredictResult) -> None:
        self.prompt_tokens += result.prompt_tokens
        self.output_tokens += result.output_tokens
        self.calls += 1
        if result.error:
            self.errors += 1

    @property
    def cost_usd(self) -> float:
        return (
            self.prompt_tokens / 1_000_000 * PRICE_INPUT_PER_M
            + self.output_tokens / 1_000_000 * PRICE_OUTPUT_PER_M
        )


def _client() -> genai.Client:
    return genai.Client(
        vertexai=True,
        project=GCP_PROJECT,
        location=GCP_LOCATION,
        credentials=vertex_credentials(),
    )


DEFAULT_HISTORY_HEADING = "This person's previous actions on this task:"


def build_prompt(
    task: str,
    website: str,
    candidates: list[str],
    history: list[str] | None,
    history_heading: str = DEFAULT_HISTORY_HEADING,
    number_history: bool = True,
) -> str:
    lines = [
        f"Task: {task}",
        f"Website: {website}",
        "",
        "Current page elements:",
    ]
    for i, cand in enumerate(candidates, start=1):
        lines.append(f"{i}. {cand}")
    if history:
        lines.append("")
        lines.append(history_heading)
        for i, h in enumerate(history, start=1):
            lines.append(f"{i}. {h}" if number_history else h)
    else:
        lines.append("")
        lines.append("No action history is available. Predict the next action from the task and page only.")
    lines.append("")
    lines.append(
        'Respond as JSON: {"element_index": <1-based integer>, "action": "CLICK"|"TYPE"|"SELECT", "value": <string or null>}'
    )
    return "\n".join(lines)


def _parse(text: str) -> tuple[int | None, str | None, str | None]:
    if not text:
        return None, None, None
    blob = text.strip()
    match = re.search(r"\{.*\}", blob, re.S)
    if match:
        blob = match.group(0)
    try:
        obj = json.loads(blob)
    except json.JSONDecodeError:
        return None, None, None
    idx = obj.get("element_index")
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        idx = None
    action = obj.get("action")
    if isinstance(action, str):
        action = action.strip().upper()
        if action not in {"CLICK", "TYPE", "SELECT"}:
            action = None
    else:
        action = None
    value = obj.get("value")
    if value is not None:
        value = str(value)
    return idx, action, value


def predict_next_action(
    task: str,
    website: str,
    candidates: list[str],
    history: list[str] | None,
    client: genai.Client | None = None,
    history_heading: str = DEFAULT_HISTORY_HEADING,
    number_history: bool = True,
) -> PredictResult:
    prompt = build_prompt(
        task,
        website,
        candidates,
        history,
        history_heading=history_heading,
        number_history=number_history,
    )
    cli = client or _client()
    try:
        resp = cli.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                temperature=0,
                max_output_tokens=128,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:  # noqa: BLE001 — surface API failures as scored misses
        return PredictResult(None, None, None, "", error=str(exc)[:400])

    text = resp.text or ""
    usage = resp.usage_metadata
    prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
    idx, action, value = _parse(text)
    if idx is not None and not (1 <= idx <= len(candidates)):
        idx = None
    return PredictResult(
        element_index=idx,
        action=action,
        value=value,
        raw=text,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
    )
