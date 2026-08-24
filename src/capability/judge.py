"""Task-success judge for capability bakeoff.

Judges FINAL STATE against the stated task constraints.
Does NOT require matching the Mind2Web human path.
"""

from __future__ import annotations

import json
import re

from google import genai
from google.genai import types

from auth import invalidate_credentials, vertex_credentials
from config import GCP_PROJECT, MODEL, PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M

JUDGE_MODEL = MODEL  # gemini-2.5-flash — cheap, sufficient for judging
JUDGE_LOCATION = "us-central1"

VALID_STATUSES = frozenset({"SUCCESS", "FAILURE", "AMBIGUOUS", "BLOCKED", "SITE_CHANGED"})

# A judge that could not run is not the same as a trajectory the judge could not
# decide. Keep them distinct so unscoreable runs never silently count as failures.
JUDGE_ERROR = "JUDGE_ERROR"

_AUTH_ERROR_MARKERS = ("UNAUTHENTICATED", "401", "invalid authentication", "expired")

JUDGE_SYSTEM = """You are a strict task-completion judge for a web agent.
You see the original task, the final URL, a short action summary, and optionally a final screenshot.
Decide whether the FINAL page state satisfies EVERY constraint in the task.

Rules:
- SUCCESS only if all stated constraints appear satisfied on the final page.
- Reaching a category page is NOT enough if filters/values were required.
- Searching is NOT enough if the task asked to open a specific item or click Follow.
- If the site blocked the agent (CAPTCHA, login wall, access denied), use BLOCKED.
- If the live site no longer supports the historical task, use SITE_CHANGED.
- If evidence is insufficient to decide, use AMBIGUOUS.
- Ignore whether the path matched a recorded human demo.

Return JSON only:
{"status":"SUCCESS"|"FAILURE"|"AMBIGUOUS"|"BLOCKED"|"SITE_CHANGED","reason":"...","evidence":"..."}
"""


def _is_auth_error(exc: Exception) -> bool:
    text = str(exc)
    return any(marker.lower() in text.lower() for marker in _AUTH_ERROR_MARKERS)


def judge_task(
    task: str,
    final_url: str,
    action_summary: str,
    screenshot_png: bytes | None = None,
    end_title: str = "",
) -> dict:
    """Score one trajectory. Retries once on auth failure with fresh credentials."""
    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            return _judge_once(task, final_url, action_summary, screenshot_png, end_title)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == 1 and _is_auth_error(exc):
                # Long runs outlive a bare access token; re-mint and try again.
                invalidate_credentials()
                continue
            break
    return {
        "status": JUDGE_ERROR,
        "reason": f"judge_error: {last_exc}"[:400],
        "evidence": "",
        "prompt_tokens": 0,
        "output_tokens": 0,
        "estimated_cost_usd": 0.0,
    }


def _judge_once(
    task: str,
    final_url: str,
    action_summary: str,
    screenshot_png: bytes | None,
    end_title: str,
) -> dict:
    client = genai.Client(
        vertexai=True,
        project=GCP_PROJECT,
        location=JUDGE_LOCATION,
        credentials=vertex_credentials(),
    )
    text = (
        f"Task:\n{task}\n\n"
        f"Final URL: {final_url}\n"
        f"Final page title: {end_title}\n\n"
        f"Action summary:\n{action_summary}\n"
    )
    parts: list = [types.Part.from_text(text=text)]
    if screenshot_png:
        parts.append(types.Part.from_bytes(data=screenshot_png, mime_type="image/png"))
    resp = client.models.generate_content(
        model=JUDGE_MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=JUDGE_SYSTEM,
            temperature=0,
            max_output_tokens=256,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            response_mime_type="application/json",
        ),
    )
    usage = resp.usage_metadata
    prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
    raw = resp.text or ""
    match = re.search(r"\{.*\}", raw, re.S)
    obj = json.loads(match.group(0) if match else raw)
    status = str(obj.get("status", "AMBIGUOUS")).upper()
    if status not in VALID_STATUSES:
        status = "AMBIGUOUS"
    return {
        "status": status,
        "reason": str(obj.get("reason") or "")[:500],
        "evidence": str(obj.get("evidence") or "")[:500],
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": (
            prompt_tokens / 1e6 * PRICE_INPUT_PER_M
            + output_tokens / 1e6 * PRICE_OUTPUT_PER_M
        ),
    }
