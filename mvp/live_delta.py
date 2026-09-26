"""Small, cursor-based live view of a running study for the home-page poll.

The full ``/api/studies/<id>`` payload is ~2MB by the end of a 24-agent run
(every step's accessibility tree, twice, plus agent_results). Polling it every
1.5s put 2-3s between a published first click and the UI showing it.

``live_view(study, since)`` returns the study's small fields every time and
only the agents (and finished results) whose display fields changed after the
cursor ``since``. Rows drop the heavy judge-only fields (accessibility trees,
state_sig, final_dom). The client merges rows by ``agent_id``.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from typing import Any

# Judge / report-only fields. The home page never reads them.
HEAVY_KEYS = frozenset(
    {
        "accessibility_tree",
        "ax_tree",
        "ax_text",
        "final_dom",
        "state_sig",
        "dom",
        "html",
        "screenshot_data_url",
    }
)
LIVE_STATUSES = frozenset({"running", "pending", "queued", "starting"})
_MAX_STUDIES = 64


class _Cursor:
    __slots__ = ("rev", "rows", "brief", "touched")

    def __init__(self) -> None:
        self.rev = 0
        self.rows: dict[str, tuple[str, int]] = {}
        self.brief: tuple[str, int] = ("", 0)
        self.touched = time.monotonic()


_CURSORS: "OrderedDict[str, _Cursor]" = OrderedDict()


def _cursor(study_id: str) -> _Cursor:
    cur = _CURSORS.get(study_id)
    if cur is None:
        cur = _Cursor()
        _CURSORS[study_id] = cur
        while len(_CURSORS) > _MAX_STUDIES:
            _CURSORS.popitem(last=False)
    else:
        _CURSORS.move_to_end(study_id)
    cur.touched = time.monotonic()
    return cur


def lite_row(row: dict[str, Any]) -> dict[str, Any]:
    """An agent row without judge-only fields; steps keep action, thought, url, screenshot."""
    out = {k: v for k, v in row.items() if k not in HEAVY_KEYS}
    trace = row.get("trace")
    if isinstance(trace, list):
        out["trace"] = [
            {k: v for k, v in step.items() if k not in HEAVY_KEYS} if isinstance(step, dict) else step
            for step in trace
        ]
    thoughts = row.get("live_thoughts")
    if isinstance(thoughts, list):
        out["live_thoughts"] = thoughts[-8:]
    return out


def _sig(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=12).hexdigest()


def _bump(cur: _Cursor, key: str, value: Any) -> int:
    sig = _sig(value)
    old = cur.rows.get(key)
    if old and old[0] == sig:
        return old[1]
    cur.rev += 1
    cur.rows[key] = (sig, cur.rev)
    return cur.rev


def live_view(study: Any, since: int = 0) -> dict[str, Any]:
    """Small fields always; brief, agents and results only when changed after ``since``."""
    from mvp.study import _json_safe, _ordered_live_sessions

    cur = _cursor(str(study.id))
    since = int(since or 0)
    if since < 0 or since > cur.rev:
        # A restarted server or a foreign cursor: send everything.
        since = 0

    sessions = [lite_row(_json_safe(s)) for s in _ordered_live_sessions(study)]
    results = [
        lite_row(_json_safe(r))
        for r in (study.agent_results or [])
        if isinstance(r, dict)
    ]
    brief = _json_safe(
        {
            "segment": study.segment,
            "personas": study.personas,
            "tasks": study.tasks,
            "competitors": study.competitors,
            "skip_competitors": study.skip_competitors,
        }
    )

    changed_sessions = []
    for s in sessions:
        aid = str(s.get("agent_id") or "")
        if _bump(cur, f"s:{aid}", s) > since:
            changed_sessions.append(s)
    changed_results = []
    for r in results:
        aid = str(r.get("agent_id") or r.get("task_id") or "")
        if _bump(cur, f"r:{aid}", r) > since:
            changed_results.append(r)
    brief_rev = _bump(cur, "brief", brief)

    log = list(study.activity_log or [])[-20:]
    out: dict[str, Any] = _json_safe(
        {
            "id": study.id,
            "url": study.url,
            "status": study.status,
            "phase": study.phase,
            "error": study.error,
            "created_at": study.created_at,
            "updated_at": study.updated_at,
            "created_at_ts": study.created_at_ts,
            "time_to_first_value_s": study.time_to_first_value_s,
            "time_to_first_value_agent": study.time_to_first_value_agent,
            "queue_eta_s": study.queue_eta_s,
            "queue_position": study.queue_position,
            "queued_s": study.queued_s,
            "test_mode": study.test_mode,
            "kill_requested": study.kill_requested,
            "access_backend": study.access_backend,
            "browserbase_session_url": study.browserbase_session_url,
            "activity_log": log,
        }
    )
    out.update(
        {
            "delta": True,
            "rev": cur.rev,
            "since": since,
            "session_order": [str(s.get("agent_id") or "") for s in sessions],
            "result_order": [str(r.get("agent_id") or r.get("task_id") or "") for r in results],
            "live_sessions": changed_sessions,
            "agent_results": changed_results,
            # Terminal studies: the client fetches the full study once for the summary.
            "final": str(study.status or "") not in LIVE_STATUSES,
        }
    )
    if brief_rev > since:
        out["brief"] = brief
    return out
