"""First-frame screenshots: upload to GCS before the UI can request them."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any


def png_data_url(path: Path | str) -> str | None:
    """Inline PNG so the live stream can paint pixels without a second GET."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    if len(raw) < 100:
        return None
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def drop_inline_shots(payload: Any) -> Any:
    """Strip bulky data URLs before writing study.json to GCS."""
    if isinstance(payload, dict):
        out = {k: drop_inline_shots(v) for k, v in payload.items() if k != "screenshot_data_url"}
        return out
    if isinstance(payload, list):
        return [drop_inline_shots(v) for v in payload]
    return payload


def drop_inline_shots_inplace(payload: Any) -> None:
    if isinstance(payload, dict):
        payload.pop("screenshot_data_url", None)
        for value in list(payload.values()):
            drop_inline_shots_inplace(value)
    elif isinstance(payload, list):
        for value in payload:
            drop_inline_shots_inplace(value)


def strip_live_view(session: dict[str, Any]) -> dict[str, Any]:
    """Browserbase live iframes render about:blank / 'watching…' — never send them."""
    session.pop("live_view_url", None)
    session.pop("live_url", None)
    session.pop("debugger_url", None)
    return session


async def upload_screenshot(study_id: str, agent_id: str, local: Path) -> bool:
    if not local.is_file() or local.stat().st_size < 100:
        return False
    try:
        from mvp.gcs_store import gcs_upload_file, screenshot_gcs_uri

        await asyncio.to_thread(
            gcs_upload_file,
            local,
            screenshot_gcs_uri(study_id, agent_id, local.name),
            content_type="image/png",
        )
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"screenshot GCS upload failed: {exc!r}", flush=True)
        return False


async def attach_opening_pixels(
    *,
    study_id: str,
    agent_id: str,
    local: Path,
    step: dict[str, Any],
) -> dict[str, Any]:
    """Upload first, then add an inline data URL so the stream paints immediately."""
    await upload_screenshot(study_id, agent_id, local)
    if step.get("step") == 0:
        data = png_data_url(local)
        if data:
            step["screenshot_data_url"] = data
    return step
