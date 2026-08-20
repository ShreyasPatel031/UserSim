"""Shared constants / pricing for capability bakeoff."""

from __future__ import annotations

from pathlib import Path

from config import RESULTS_DIR, ROOT

VIEWPORT = {"width": 1280, "height": 800}
MAX_ACTIONS = 20
BAKEOFF_MODEL = "gemini-3.6-flash"
BAKEOFF_LOCATION = "global"  # 3.6 Flash is served from global, not us-central1

# Vertex list prices USD / 1M tokens (from user brief)
PRICE = {
    "gemini-3.6-flash": {"in": 1.50, "out": 7.50},
    "gemini-3-flash-preview": {"in": 0.50, "out": 3.00},
    "gemini-3.1-pro-preview": {"in": 2.00, "out": 12.00},  # approximate; log actual
    "gemini-2.5-flash": {"in": 0.30, "out": 2.50},
}

OUT_DIR = RESULTS_DIR / "capability"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def cost_usd(model: str, prompt_tokens: int, output_tokens: int) -> float:
    p = PRICE.get(model, PRICE["gemini-3.6-flash"])
    return prompt_tokens / 1e6 * p["in"] + output_tokens / 1e6 * p["out"]


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

CAPABLE_AGENT_PREAMBLE = (
    "You are a capable web agent. Complete the user's task fully. "
    "Satisfy every constraint in the task (filters, values, final actions). "
    "Do not stop early once you reach a related category page. "
    "Use up to the allowed number of browser actions. "
    "When the task is fully complete, stop and briefly state what you accomplished."
)
