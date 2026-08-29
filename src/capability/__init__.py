"""Shared constants / pricing for capability bakeoff."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

from config import GCP_LOCATION, MODEL, RESULTS_DIR, ROOT

VIEWPORT = {"width": 1280, "height": 800}

# Step budget is derived from Mind2Web human trajectories — not an arbitrary round number.
_tasks_path = ROOT / "data" / "mind2web_tasks.json"
if _tasks_path.is_file():
    _TASKS = json.loads(_tasks_path.read_text())["tasks"]
else:
    _TASKS = [{"n_steps": 22}]
MAX_HUMAN_STEPS = max(int(t.get("n_steps") or 0) for t in _TASKS)
# Buffer: +50% of the longest human path, at least +10 steps.
ACTION_BUFFER = max(10, math.ceil(0.5 * MAX_HUMAN_STEPS))
# 1.5x the longest human path (33) turned out to be far too tight for a small model, which
# needs recovery headroom a human does not: on full100 it cut off 93% of failures and 3 of 6
# successes finished right at the cap. Webwright's published curve knees around 50 steps.
LEGACY_MAX_ACTIONS = MAX_HUMAN_STEPS + ACTION_BUFFER  # 22 + 11 = 33
# Default step budget for Browser Use fleet runs (override with --max-actions / MAX_ACTIONS).
PARALLEL_ARM_MAX_ACTIONS = 60
MAX_ACTIONS = int(
    os.environ.get("CAPABILITY_MAX_ACTIONS")
    or os.environ.get("BROWSER_USE_MAX_ACTIONS")
    or PARALLEL_ARM_MAX_ACTIONS
)

# Default agent model for all capability testing (matches config.MODEL / judge).
BAKEOFF_MODEL = MODEL
BAKEOFF_LOCATION = GCP_LOCATION  # us-central1 for 2.5 Flash

MODEL_LOCATION = {
    "gemini-3.6-flash": "global",
    "gemini-3-flash-preview": "global",
    "gemini-3.1-pro-preview": "global",
    "gemini-2.5-flash": "us-central1",
    "gemini-2.5-flash-lite": "us-central1",
}


def location_for(model: str) -> str:
    return MODEL_LOCATION.get(model, BAKEOFF_LOCATION)


# Vertex list prices USD / 1M tokens (from user brief)
PRICE = {
    "gemini-3.6-flash": {"in": 1.50, "out": 7.50},
    "gemini-3-flash-preview": {"in": 0.50, "out": 3.00},
    "gemini-3.1-pro-preview": {"in": 2.00, "out": 12.00},  # approximate; log actual
    "gemini-2.5-flash": {"in": 0.30, "out": 2.50},
    "gemini-2.5-flash-lite": {"in": 0.10, "out": 0.40},
}

if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
    OUT_DIR = Path("/tmp/usersim-capability")
else:
    OUT_DIR = RESULTS_DIR / "capability"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def cost_usd(model: str, prompt_tokens: int, output_tokens: int) -> float:
    p = PRICE.get(model, PRICE[MODEL])
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
