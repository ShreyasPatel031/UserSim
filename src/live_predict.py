"""Predict the next action on a live page (task + screenshot/DOM + history)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from google import genai
from google.genai import types

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auth import vertex_credentials
from config import GCP_LOCATION, GCP_PROJECT, MODEL
from model import PredictResult, TokenMeter, _parse


AGENT_LIVE_SYSTEM = """You are a web agent. Your goal is to successfully complete the user's task on this live website.
You see a screenshot and a numbered list of interactive elements.
Pick exactly one next action: CLICK, TYPE, SELECT, or STOP.
For TYPE, set value to the text to type. For SELECT, set value to the option. For CLICK/STOP, value must be null.
Use element_index 0 only with STOP.
Keep going if more interaction could help finish the task. Reply STOP only when the task is complete.
Return JSON only."""

USERSIM_LIVE_SYSTEM = """You simulate a normal human using a public website.
You see a screenshot and a numbered list of interactive elements.
Predict the next action that person would take: CLICK, TYPE, SELECT, or STOP.
For TYPE, set value to the text they would type. For SELECT, set value to the option. For CLICK/STOP, value must be null.
Use element_index 0 only with STOP.
Do not optimize for task completion. Humans often stop once they believe they have done enough, even if a thorough agent would keep going.
Prefer obvious, visible controls a person would actually use.
Return JSON only."""

CONDITIONS = {
    "agent": AGENT_LIVE_SYSTEM,
    "usersim": USERSIM_LIVE_SYSTEM,
}


def predict_live(
    task: str,
    url: str,
    candidates: list[str],
    history: list[str],
    screenshot_png: bytes | None = None,
    condition: str = "usersim",
    client: genai.Client | None = None,
) -> PredictResult:
    system = CONDITIONS.get(condition, USERSIM_LIVE_SYSTEM)
    cli = client or genai.Client(
        vertexai=True,
        project=GCP_PROJECT,
        location=GCP_LOCATION,
        credentials=vertex_credentials(),
    )
    text = [
        f"Task: {task}",
        f"Current URL: {url}",
        "",
        "Current page elements:",
    ]
    for i, cand in enumerate(candidates, start=1):
        text.append(f"{i}. {cand}")
    text.append("")
    if history:
        text.append("Actions taken so far:")
        for i, h in enumerate(history, start=1):
            text.append(f"{i}. {h}")
    else:
        text.append("No previous actions yet (this is the first step).")
    text.append("")
    text.append(
        'Respond as JSON: {"element_index": <1-based integer or 0 to STOP>, '
        '"action": "CLICK"|"TYPE"|"SELECT"|"STOP", "value": <string or null>}'
    )
    parts: list = [types.Part.from_text(text="\n".join(text))]
    if screenshot_png:
        parts.insert(0, types.Part.from_bytes(data=screenshot_png, mime_type="image/png"))
    try:
        resp = cli.models.generate_content(
            model=MODEL,
            contents=parts,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0,
                max_output_tokens=192,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return PredictResult(None, None, None, "", error=str(exc)[:400])

    raw = resp.text or ""
    usage = resp.usage_metadata
    idx, action, value = _parse(raw)
    # Allow STOP in live parse (offline _parse rejects it)
    if action is None:
        try:
            obj = json.loads(raw)
            a = str(obj.get("action") or "").upper()
            if a == "STOP":
                action = "STOP"
                idx = 0
            if value is None and obj.get("value") is not None:
                value = str(obj.get("value"))
            if idx is None and obj.get("element_index") is not None:
                idx = int(obj["element_index"])
        except Exception:  # noqa: BLE001
            if "STOP" in raw.upper():
                action = "STOP"
                idx = 0
    if action == "STOP":
        idx = 0
    return PredictResult(
        element_index=idx,
        action=action,
        value=value,
        raw=raw,
        prompt_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
        output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
    )


if __name__ == "__main__":
    payload = json.loads(sys.stdin.read())
    png = None
    shot = payload.get("screenshot_path")
    if shot:
        png = Path(shot).read_bytes()
    pred = predict_live(
        task=payload["task"],
        url=payload.get("url", ""),
        candidates=payload["candidates"],
        history=payload.get("history") or [],
        screenshot_png=png,
        condition=payload.get("condition", "usersim"),
    )
    print(
        json.dumps(
            {
                "element_index": pred.element_index,
                "action": pred.action,
                "value": pred.value,
                "raw": pred.raw,
                "error": pred.error,
                "prompt_tokens": pred.prompt_tokens,
                "output_tokens": pred.output_tokens,
            }
        )
    )
