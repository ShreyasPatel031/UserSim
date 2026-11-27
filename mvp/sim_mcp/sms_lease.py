"""One SMS phone number, one session at a time.

The MCP's SMS number is the owner's real phone (texts forwarded over ntfy), so it is leased: usersim_signup_phone
gives the number to one session for sms_lease_s seconds (limits.json) or until that session closes. Another
session asking meanwhile joins a first-come queue: usersim_signup_phone waits up to sms_queue_wait_s for the number
and only then answers "busy, retry in N s" (keeping the caller's place in the queue). Once the holder has read its
code the lease shrinks to sms_after_code_s, so the next user is not kept waiting for the full sms_lease_s. usersim_wait_for_sms_code only reads for the session
holding the lease, only texts that arrived after that lease started, and never texts on sms_sender_denylist.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

_LOCK = threading.Lock()


@dataclass
class Lease:
    session_id: str
    owner: str
    started: float
    expires: float


_LEASE: Lease | None = None
# Sessions waiting for the number, first come first served: session_id -> (joined, last_seen).
_QUEUE: dict[str, tuple[float, float]] = {}
QUEUE_STALE_S = 90.0  # a waiter that has not asked again for this long loses its place


class Busy(Exception):
    def __init__(self, retry_s: int) -> None:
        super().__init__(f"the SMS number is busy: another simulated user holds it. Retry in {retry_s} s "
                         "(call usersim_signup_phone again then), or continue without SMS if the site allows it")
        self.retry_s = retry_s


def _live(lease: Lease | None, sessions: dict[str, Any], now: float) -> bool:
    if lease is None or now >= lease.expires:
        return False
    sim = sessions.get(lease.session_id)
    return sim is not None and not getattr(sim, "closed", False)


def _prune_queue(sessions: dict[str, Any], now: float) -> None:
    for sid, (_, seen) in list(_QUEUE.items()):
        sim = sessions.get(sid)
        if sim is None or getattr(sim, "closed", False) or now - seen > QUEUE_STALE_S:
            _QUEUE.pop(sid, None)


def _ahead(session_id: str) -> int:
    """How many waiters joined before this session (0 = next in line or not queued)."""
    mine = _QUEUE.get(session_id)
    if mine is None:
        return len(_QUEUE)
    return sum(1 for sid, (joined, _) in _QUEUE.items() if sid != session_id and joined < mine[0])


def acquire(session_id: str, owner: str, ttl_s: float, sessions: dict[str, Any], *, on_new: Any = None) -> tuple[Lease, bool]:
    """(lease, new). The same session asking again keeps its lease (same start, so texts already received stay
    readable) and gets the expiry extended. on_new() runs before a new lease is granted (e.g. the per-IP daily
    count) and may raise to refuse it."""
    global _LEASE
    now = time.time()
    with _LOCK:
        cur = _LEASE
        if _live(cur, sessions, now) and cur.session_id == session_id:
            cur.expires = now + ttl_s
            return cur, False
        _prune_queue(sessions, now)
        busy = _live(cur, sessions, now)
        if busy or _ahead(session_id) > 0:
            joined = _QUEUE.get(session_id, (now, now))[0]
            _QUEUE[session_id] = (joined, now)
            wait = int(cur.expires - now) + 1 if busy else 5
            raise Busy(max(1, wait))
        if on_new is not None:
            on_new()
        _QUEUE.pop(session_id, None)
        _LEASE = Lease(session_id=session_id, owner=owner, started=now, expires=now + ttl_s)
        return _LEASE, True


def shorten(session_id: str, keep_s: float) -> None:
    """The holder got its code: keep the lease only keep_s more seconds (a wrong code or a resend), then free it."""
    with _LOCK:
        if _LEASE is not None and _LEASE.session_id == session_id:
            _LEASE.expires = min(_LEASE.expires, time.time() + max(0.0, keep_s))


def leave_queue(session_id: str) -> None:
    with _LOCK:
        _QUEUE.pop(session_id, None)


def held_by(session_id: str, sessions: dict[str, Any]) -> Lease | None:
    """The lease if this session holds it right now, else None."""
    with _LOCK:
        cur = _LEASE
        if _live(cur, sessions, time.time()) and cur.session_id == session_id:
            return cur
        return None


def release(session_id: str) -> None:
    global _LEASE
    with _LOCK:
        _QUEUE.pop(session_id, None)
        if _LEASE is not None and _LEASE.session_id == session_id:
            _LEASE = None


def status(sessions: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        cur = _LEASE
        now = time.time()
        _prune_queue(sessions, now)
        if not _live(cur, sessions, now):
            return {"busy": False, "waiting": len(_QUEUE)}
        return {"busy": True, "seconds_left": int(cur.expires - now), "waiting": len(_QUEUE)}


def reset_for_tests() -> None:
    global _LEASE
    with _LOCK:
        _LEASE = None
        _QUEUE.clear()
