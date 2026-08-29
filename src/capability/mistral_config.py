"""Mistral API helpers for MVP agents."""

from __future__ import annotations

import os

MISTRAL_API_BASE = os.environ.get("MISTRAL_API_BASE", "https://api.mistral.ai/v1").rstrip("/")


def mistral_api_key() -> str:
    key = (os.environ.get("MISTRAL_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("MISTRAL_API_KEY is not set")
    return key


def mistral_model() -> str:
    return (os.environ.get("MISTRAL_MODEL") or "mistral-small-latest").strip()
