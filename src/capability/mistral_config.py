"""Mistral hackathon defaults — multimodal models for Browser Use."""

from __future__ import annotations

import os
from pathlib import Path

from config import ROOT

# Vision + agentic multimodal (La Plateforme). Override via MISTRAL_MODEL env.
DEFAULT_MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "pixtral-large-2411")
MISTRAL_API_BASE = os.environ.get("MISTRAL_API_BASE", "https://api.mistral.ai/v1")

# USD / 1M tokens (La Plateforme list, approximate — log actual usage)
MISTRAL_PRICE = {
    "ministral-3b-latest": {"in": 0.10, "out": 0.10},
    "ministral-8b-latest": {"in": 0.15, "out": 0.15},
    "ministral-14b-latest": {"in": 0.20, "out": 0.20},
    "mistral-small-latest": {"in": 0.15, "out": 0.60},
    "mistral-small-2603": {"in": 0.15, "out": 0.60},
    "pixtral-large-2411": {"in": 2.00, "out": 6.00},
    "pixtral-12b-2409": {"in": 0.15, "out": 0.15},
    "mistral-medium-2508": {"in": 0.40, "out": 2.00},
    "mistral-large-2411": {"in": 2.00, "out": 6.00},
    "mistral-vibe-cli-latest": {"in": 1.50, "out": 7.50},
}


def _read_secret(name: str, default: str = "") -> str:
    val = os.environ.get(name, "").strip()
    if val:
        return val
    env_file = ROOT / "secrets" / "env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return default


def mistral_model() -> str:
    return _read_secret("MISTRAL_MODEL", "mistral-small-2603")


def mistral_api_key() -> str:
    key = _read_secret("MISTRAL_API_KEY")
    if key:
        return key
    raise RuntimeError(
        "Set MISTRAL_API_KEY in secrets/env or the environment (console.mistral.ai)."
    )


def mistral_cost_usd(model: str, prompt_tokens: int, output_tokens: int) -> float:
    p = MISTRAL_PRICE.get(model, MISTRAL_PRICE[DEFAULT_MISTRAL_MODEL])
    return prompt_tokens / 1e6 * p["in"] + output_tokens / 1e6 * p["out"]
