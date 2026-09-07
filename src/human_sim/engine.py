"""Gemini-backed classical human simulator engine."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types

from auth import vertex_credentials
from config import GCP_LOCATION, GCP_PROJECT, MODEL, PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M
from human_sim.persona import Persona
from human_sim.prompts import SYSTEM, build_user_prompt
from human_sim.situation import Situation


@dataclass
class SimulateResult:
    kind: str
    choice_id: str | None = None
    rating: int | None = None
    text: str | None = None
    confidence: float | None = None
    rationale: str = ""
    raw: str = ""
    prompt_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    model: str = MODEL

    @property
    def cost_usd(self) -> float:
        return (
            self.prompt_tokens / 1_000_000 * PRICE_INPUT_PER_M
            + self.output_tokens / 1_000_000 * PRICE_OUTPUT_PER_M
        )


@dataclass
class HumanSimulator:
    """Persona-conditioned decision head. Swap MODEL via constructor for ablations."""

    model: str = MODEL
    temperature: float = 0.4
    _client: Any = field(default=None, repr=False)

    def _get_client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(
                vertexai=True,
                project=GCP_PROJECT,
                location=GCP_LOCATION,
                credentials=vertex_credentials(),
            )
        return self._client

    def decide(self, persona: Persona, situation: Situation) -> SimulateResult:
        user = build_user_prompt(persona, situation)
        try:
            resp = self._get_client().models.generate_content(
                model=self.model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM,
                    temperature=self.temperature,
                    response_mime_type="application/json",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return SimulateResult(kind=situation.kind, error=str(exc)[:400], model=self.model)

        raw = (resp.text or "").strip()
        usage = getattr(resp, "usage_metadata", None)
        prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        parsed = _parse_json(raw)
        if parsed is None:
            return SimulateResult(
                kind=situation.kind,
                raw=raw,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                error="unparseable_json",
                model=self.model,
            )

        conf = parsed.get("confidence")
        try:
            confidence = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            confidence = None

        return SimulateResult(
            kind=situation.kind,
            choice_id=_as_str(parsed.get("choice_id")),
            rating=_as_int(parsed.get("rating")),
            text=_as_str(parsed.get("text")),
            confidence=confidence,
            rationale=_as_str(parsed.get("rationale")) or "",
            raw=raw,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            model=self.model,
        )


def _parse_json(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _as_str(v: Any) -> str | None:
    if v is None:
        return None
    return str(v)


def _as_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
