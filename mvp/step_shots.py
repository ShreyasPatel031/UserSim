"""One small JPEG per trace step, captured beside the step and uploaded in the background.

The trace viewer used to show "No screenshot for this step. The agent read
the page as text" for every step but the last: agents saved only final.png.
Now each step's page is captured (viewport JPEG, quality MVP_STEP_SHOT_QUALITY,
default 45, about 50-120 KB) while the model decides, and uploaded to GCS off
the event loop. ``row["screenshot_url"]`` is set once the upload lands; the
agent drains pending uploads (bounded wait) before its result is saved.

MVP_STEP_SHOTS=0 turns it off.
"""

from __future__ import annotations

import asyncio
import os
import time
import weakref
from contextvars import ContextVar
from typing import Any

STUDY: ContextVar[str] = ContextVar("step_shot_study", default="")
_PENDING: dict[str, set[asyncio.Task]] = {}
STATS: dict[str, int] = {"captured": 0, "uploaded": 0, "failed": 0, "retried": 0}
# One capture at a time per page: two overlapping page.screenshot calls (the
# step-0 shot and the first model step's shot) made the second one fail.
_LOCKS: "weakref.WeakKeyDictionary[Any, asyncio.Lock]" = weakref.WeakKeyDictionary()


def _lock(page: Any) -> asyncio.Lock | None:
    try:
        lock = _LOCKS.get(page)
        if lock is None:
            lock = _LOCKS[page] = asyncio.Lock()
        return lock
    except TypeError:
        return None


def enabled() -> bool:
    return os.environ.get("MVP_STEP_SHOTS", "1").strip().lower() not in {"0", "false", "no"}


def _quality() -> int:
    try:
        return max(20, min(90, int(os.environ.get("MVP_STEP_SHOT_QUALITY") or 45)))
    except ValueError:
        return 45


def shot_name(step: int, suffix: str = "") -> str:
    return f"step_{int(step)}{('_' + suffix) if suffix else ''}.jpg"


def shot_url(study_id: str, agent_id: str, step: int, suffix: str = "") -> str:
    return f"/api/studies/{study_id}/agents/{agent_id}/screenshots/{shot_name(step, suffix)}"


async def _shoot(page: Any, timeout_s: float) -> bytes | None:
    try:
        return await page.screenshot(
            type="jpeg", quality=_quality(), full_page=False, scale="css", timeout=int(timeout_s * 1000)
        )
    except Exception:  # noqa: BLE001
        return None


async def capture(page: Any, timeout_s: float = 4.0) -> bytes | None:
    lock = _lock(page)
    if lock is None:
        blob = await _shoot(page, timeout_s)
    else:
        async with lock:
            blob = await _shoot(page, timeout_s)
    if blob:
        STATS["captured"] += 1
    return blob or None


def start_capture(page: Any) -> asyncio.Task | None:
    """Begin capturing the current page now (runs beside the model call)."""
    if page is None or not enabled() or not STUDY.get():
        return None
    try:
        return asyncio.get_running_loop().create_task(capture(page))
    except RuntimeError:
        return None


def _upload(study_id: str, agent_id: str, step: int, blob: bytes, suffix: str = "") -> bool:
    from mvp.gcs_store import gcs_upload_bytes, screenshot_gcs_uri
    from mvp.paths import MVP_RUNS_DIR

    name = shot_name(step, suffix)
    try:
        dest = MVP_RUNS_DIR / study_id / agent_id / "screenshots"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / name).write_bytes(blob)
    except OSError:
        pass
    for attempt in range(2):
        try:
            gcs_upload_bytes(screenshot_gcs_uri(study_id, agent_id, name), blob, content_type="image/jpeg")
            return True
        except Exception as exc:  # noqa: BLE001
            if attempt:
                print(f"[{agent_id}] step {step} screenshot upload failed: {exc!r}", flush=True)
            time.sleep(0.5)
    return False


def attach(
    task: asyncio.Task | None,
    row: dict[str, Any],
    agent_id: str,
    step: int,
    suffix: str = "",
    page: Any = None,
) -> None:
    """When ``task`` has the JPEG, upload it and point ``row`` at it.

    With ``page``, a failed capture (the step's click navigated away while the
    shot was in flight) is retried once on the page as it is now, so every
    step still gets an image; the row is marked ``screenshot_after_action``.
    """
    study_id = STUDY.get()
    if not study_id or not isinstance(row, dict) or (task is None and page is None):
        return

    async def _finish() -> None:
        blob = None
        if task is not None:
            try:
                blob = await task
            except Exception:  # noqa: BLE001
                blob = None
        if not blob and page is not None and enabled():
            await asyncio.sleep(0.4)
            blob = await capture(page, timeout_s=8.0)
            if blob:
                STATS["retried"] += 1
                row["screenshot_after_action"] = True
        if not blob:
            STATS["failed"] += 1
            return
        ok = await asyncio.to_thread(_upload, study_id, agent_id, step, blob, suffix)
        if ok:
            STATS["uploaded"] += 1
            # A final.png set on the last step wins; do not overwrite it.
            if not row.get("final_screenshot_url"):
                row["screenshot_url"] = shot_url(study_id, agent_id, step, suffix)
            row["step_screenshot_url"] = shot_url(study_id, agent_id, step, suffix)
        else:
            STATS["failed"] += 1

    key = f"{study_id}:{agent_id}"
    try:
        up = asyncio.get_running_loop().create_task(_finish())
    except RuntimeError:
        return
    bucket = _PENDING.setdefault(key, set())
    bucket.add(up)
    up.add_done_callback(bucket.discard)


def shot_now(page: Any, row: dict[str, Any], agent_id: str, step: int, suffix: str = "") -> None:
    attach(start_capture(page), row, agent_id, step, suffix, page=page)


async def drain(agent_id: str, timeout_s: float = 8.0) -> int:
    """Wait (bounded) for this agent's pending step uploads. Returns how many were still pending."""
    key = f"{STUDY.get()}:{agent_id}"
    tasks = list(_PENDING.get(key) or [])
    if not tasks:
        return 0
    _done, pending = await asyncio.wait(tasks, timeout=timeout_s)
    return len(pending)
