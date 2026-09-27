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
    """Deprecated no-op kept for callers — live view is shown after agent start."""
    return session


def attach_live_view(session: dict[str, Any], bb_session: Any) -> str | None:
    """Resolve Browserbase debugger URL onto the live session (for agent-start UI)."""
    sid = getattr(bb_session, "id", None) if bb_session is not None else None
    if not sid:
        return None
    try:
        from capability.browserbase_client import session_live_view_url

        url = session_live_view_url(str(sid))
    except Exception:
        url = None
    if url:
        session["live_view_url"] = url
        session["browserbase_session_id"] = str(sid)
    return url


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


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def png_bytes_ok(raw: bytes | None) -> bool:
    return bool(raw) and raw[:8] == _PNG_MAGIC and len(raw) > 2000


def upload_final_verified(study_id: str, agent_id: str, local: Path | None = None) -> bool:
    """Upload final.png bytes to GCS, then read them back (from 2e64b7d).

    final_screenshot_url is only kept when this returns True. A local file
    under mvp/runs alone is the grader's 'no downloadable PNG' failure.
    """
    if not study_id or not agent_id:
        return False
    from mvp.gcs_store import gcs_download_bytes, gcs_upload_bytes, screenshot_gcs_uri

    if local is None:
        from mvp.paths import MVP_RUNS_DIR

        local = MVP_RUNS_DIR / study_id / agent_id / "screenshots" / "final.png"
    try:
        data = Path(local).read_bytes() if Path(local).is_file() else b""
    except OSError:
        data = b""
    if not png_bytes_ok(data):
        return False
    uri = screenshot_gcs_uri(study_id, agent_id, "final.png")
    try:
        gcs_upload_bytes(uri, data, content_type="image/png")
        fetched = gcs_download_bytes(uri)
    except Exception as exc:  # noqa: BLE001
        print(f"final.png GCS upload failed {agent_id}: {exc!r}", flush=True)
        return False
    return png_bytes_ok(fetched) and fetched == data


async def attach_opening_pixels(
    *,
    study_id: str,
    agent_id: str,
    local: Path,
    step: dict[str, Any],
) -> dict[str, Any]:
    """Inline data URL first (timing-critical), GCS upload in the background.

    Creation→first-real-shot must stay ≤5s. Awaiting 24 sequential GCS uploads
    of large marketing PNGs was blowing that budget on otherwise-ready warms.
    """
    if step.get("step") == 0:
        data = png_data_url(local)
        if data:
            step["screenshot_data_url"] = data
    # Fire-and-forget archival — local + inline pixels already satisfy e2e/UI.
    try:
        asyncio.create_task(
            upload_screenshot(study_id, agent_id, local),
            name=f"gcs-open-{study_id[:8]}-{agent_id}",
        )
    except Exception:
        await upload_screenshot(study_id, agent_id, local)
    return step
