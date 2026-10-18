"""One SMS phone number, one session at a time.

The MCP's SMS number is the owner's real phone (texts forwarded over ntfy), so it is leased: usersim_signup_phone
gives the number to one session for sms_lease_s seconds (limits.json) or until that session closes. Another
session asking meanwhile gets "number busy, retry in N s". usersim_wait_for_sms_code only reads for the session
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


def acquire(session_id: str, owner: str, ttl_s: float, sessions: dict[str, Any], *, on_new: Any = None) -> tuple[Lease, bool]:
    """(lease, new). The same session asking again keeps its lease (same start, so texts already received stay
    readable) and gets the expiry extended. on_new() runs before a new lease is granted (e.g. the per-IP daily
    count) and may raise to refuse it."""
    global _LEASE
    now = time.time()
    with _LOCK:
        cur = _LEASE
        if _live(cur, sessions, now):
            if cur.session_id == session_id:
                cur.expires = now + ttl_s
                return cur, False
            raise Busy(max(1, int(cur.expires - now) + 1))
        if on_new is not None:
            on_new()
        _LEASE = Lease(session_id=session_id, owner=owner, started=now, expires=now + ttl_s)
        return _LEASE, True


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
        if _LEASE is not None and _LEASE.session_id == session_id:
            _LEASE = None


def status(sessions: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        cur = _LEASE
        now = time.time()
        if not _live(cur, sessions, now):
            return {"busy": False}
        return {"busy": True, "seconds_left": int(cur.expires - now)}


def reset_for_tests() -> None:
    global _LEASE
    with _LOCK:
        _LEASE = None
