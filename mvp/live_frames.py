"""Live frame bus: seed → orchestrator/UI immediately; GCS is archival."""

from __future__ import annotations

import base64
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MVP_RUNS_DIR = Path(os.environ.get("MVP_RUNS_DIR") or (ROOT / "mvp" / "runs"))

# study_id -> list of frame dicts waiting to be drained by the fleet poller
_BUS: dict[str, list[dict[str, Any]]] = {}
_BUS_LOCK = threading.Lock()
_TOKENS: dict[str, str] = {}


def issue_live_token(study_id: str) -> str:
    token = secrets.token_urlsafe(24)
    _TOKENS[study_id] = token
    return token


def check_live_token(study_id: str, token: str | None) -> bool:
    if not token:
        return False
    expected = _TOKENS.get(study_id) or os.environ.get("MVP_LIVE_FRAME_TOKEN")
    return bool(expected) and secrets.compare_digest(str(expected), str(token))


def live_push_url_for_job(study_id: str) -> str | None:
    """Public URL seeds can POST frames to (Vercel / tunnel). Empty → SSH relay only."""
    base = (
        os.environ.get("MVP_LIVE_PUSH_URL")
        or os.environ.get("MVP_PUBLIC_BASE_URL")
        or os.environ.get("VERCEL_URL")
        or ""
    ).rstrip("/")
    if not base:
        return None
    if base.startswith("http"):
        return f"{base}/api/internal/live-frame"
    return f"https://{base}/api/internal/live-frame"


def save_frame_locally(
    *,
    study_id: str,
    agent_id: str,
    step_no: int,
    png: bytes,
    filename: str | None = None,
) -> str:
    """Write PNG under mvp/runs so /api/.../screenshots can serve without GCS."""
    name = filename or (f"step_{step_no}.png" if step_no == 0 else f"bbox_{step_no}.png")
    dest = MVP_RUNS_DIR / study_id / agent_id / "screenshots" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(png)
    return f"/api/studies/{study_id}/agents/{agent_id}/screenshots/{name}"


def publish_live_frame(
    *,
    study_id: str,
    agent_id: str,
    step: dict[str, Any],
    png: bytes | None = None,
) -> dict[str, Any]:
    """Enqueue a frame for the fleet loop / SSE; optionally persist PNG locally."""
    step_no = int(step.get("step") or 0)
    out = dict(step)
    if png:
        url = save_frame_locally(
            study_id=study_id,
            agent_id=agent_id,
            step_no=step_no,
            png=png,
            filename=Path(str(step.get("screenshot_url") or "")).name or None,
        )
        out["screenshot_url"] = url
        # Tiny data-URL fallback for consumers that don't fetch yet.
        out.setdefault(
            "screenshot_data_url",
            f"data:image/png;base64,{base64.b64encode(png).decode('ascii')}",
        )
    out["_live_at"] = time.time()
    with _BUS_LOCK:
        _BUS.setdefault(study_id, []).append({"agent_id": agent_id, "step": out})

    # Patch in-memory study immediately (SSH relay / HTTP) so GET/UI don't wait on
    # the fleet poller — and hydrate cannot race-clear an empty trace.
    try:
        from mvp.study import STUDIES

        study = STUDIES.get(study_id)
        live = getattr(study, "live_sessions", None) if study is not None else None
        sess = live.get(agent_id) if isinstance(live, dict) else None
        if isinstance(sess, dict):
            sess["status"] = "running" if sess.get("status") != "complete" else sess["status"]
            trace = list(sess.get("trace") or [])
            existing = {s.get("step"): i for i, s in enumerate(trace)}
            if out.get("step") in existing:
                trace[existing[out["step"]]] = {**trace[existing[out["step"]]], **out}
            else:
                # Keep chronological by step number when possible.
                trace.append(out)
                trace.sort(key=lambda s: int(s.get("step") or 0))
            sess["trace"] = trace
            sess["num_steps"] = len(trace)
            if out.get("action"):
                sess["last_action"] = out["action"]
            from datetime import datetime, timezone

            study.updated_at = datetime.now(timezone.utc)
    except Exception:
        pass

    return out


def drain_live_frames(study_id: str) -> list[dict[str, Any]]:
    with _BUS_LOCK:
        items = _BUS.pop(study_id, [])
        # Keep key empty list? pop removes — fine
    return items


def peek_live_frame_count(study_id: str) -> int:
    with _BUS_LOCK:
        return len(_BUS.get(study_id) or [])
