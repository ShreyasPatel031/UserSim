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
from model import PredictResult, SYSTEM, _parse


LIVE_SYSTEM = SYSTEM + """
The page may also include a screenshot. Use the screenshot and the numbered element list together.
Prefer visible, task-relevant controls a human would actually click next.
If the task is complete, return {"element_index": 0, "action": "STOP", "value": null}.
"""


def predict_live(
    task: str,
    url: str,
    candidates: list[str],
    history: list[str],
    screenshot_png: bytes | None = None,
) -> PredictResult:
    client = genai.Client(
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
        text.append("This person's previous actions:")
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
        resp = client.models.generate_content(
            model=MODEL,
            contents=parts,
            config=types.GenerateContentConfig(
                system_instruction=LIVE_SYSTEM,
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
    if action is None and "STOP" in raw.upper():
        action = "STOP"
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
