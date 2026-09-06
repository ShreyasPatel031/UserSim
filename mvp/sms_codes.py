"""Read one-time verification codes out of the macOS Messages database.

Requires iPhone "Text Message Forwarding" to this Mac, plus Full Disk Access
for whatever runs this (Terminal / the IDE), since ~/Library/Messages is
protected. Without both, SMS-based 2FA cannot be automated and the sign-in
flow falls back to pinging the phone.
"""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"

# Apple epoch (2001-01-01) offset used by Messages' `date` column.
_APPLE_EPOCH_SQL = "date/1000000000 + strftime('%s','2001-01-01')"

_CODE_RE = re.compile(r"\b(\d{6,8})\b")
_VERIFY_HINTS = (
    "google",
    "verification",
    "verify",
    "code",
    "g-",
    "youtube",
    "2-step",
)


def _message_body(text: str | None, attributed_body: bytes | None) -> str:
    """Return searchable message content across old and new Messages schemas.

    Recent macOS releases may leave ``message.text`` null and store the visible
    SMS inside the serialized ``NSAttributedString`` blob instead.  The string
    payload remains embedded as UTF-8/ASCII, so a lossy decode is sufficient
    for locating verification hints and numeric codes without deserializing an
    untrusted keyed archive.
    """
    if text:
        return text
    if not attributed_body:
        return ""
    if isinstance(attributed_body, memoryview):
        attributed_body = attributed_body.tobytes()
    if not isinstance(attributed_body, bytes):
        return ""
    return attributed_body.decode("utf-8", errors="ignore")


def messages_readable() -> tuple[bool, str]:
    """Whether the Messages DB can be read, plus a human-readable reason."""
    if not CHAT_DB.is_file():
        return False, f"{CHAT_DB} not found"
    try:
        con = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
        con.execute("select count(*) from message limit 1").fetchone()
        con.close()
        return True, "ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc} (grant Full Disk Access)"


def recent_codes(within_seconds: float = 300.0, limit: int = 20) -> list[dict]:
    """Verification codes seen in the last ``within_seconds``, newest first."""
    ok, _ = messages_readable()
    if not ok:
        return []
    cutoff = time.time() - within_seconds
    try:
        con = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
        rows = con.execute(
            f"""
            select text, attributedBody, {_APPLE_EPOCH_SQL} as ts
            from message
            where (text is not null or attributedBody is not null)
              and is_from_me = 0
            order by date desc
            limit 200
            """
        ).fetchall()
        con.close()
    except Exception:
        return []

    found: list[dict] = []
    for text, attributed_body, ts in rows:
        if ts is None or float(ts) < cutoff:
            continue
        body = _message_body(text, attributed_body)
        low = body.lower()
        if not any(h in low for h in _VERIFY_HINTS):
            continue
        # Google SMS codes look like "G-123456".
        match = re.search(r"\bG-(\d{6})\b", body) or _CODE_RE.search(body)
        if not match:
            continue
        found.append(
            {
                "code": match.group(1),
                "ts": float(ts),
                "text": body[:140],
            }
        )
        if len(found) >= limit:
            break
    return found


CODE_DROP = Path(__file__).resolve().parents[1] / "secrets" / "2fa_code.txt"


def read_dropped_code() -> str | None:
    """Code the owner pasted into secrets/2fa_code.txt, consumed once."""
    if not CODE_DROP.is_file():
        return None
    try:
        raw = CODE_DROP.read_text().strip()
    except Exception:
        return None
    match = re.search(r"(\d{6,8})", raw)
    if not match:
        return None
    try:
        CODE_DROP.unlink()
    except Exception:
        pass
    return match.group(1)


def wait_for_code(
    *,
    timeout_s: float = 180.0,
    newer_than: float | None = None,
    poll_s: float = 3.0,
) -> str | None:
    """Block until a fresh verification code is available.

    Accepts a code from forwarded SMS or from ``secrets/2fa_code.txt``, so a
    Mac without Text Message Forwarding can still be unblocked by hand.
    ``newer_than`` is the unix time the code was requested, so a stale code
    already sitting in the inbox is never reused.
    """
    started = time.time()
    floor = newer_than if newer_than is not None else started
    while time.time() - started < timeout_s:
        dropped = read_dropped_code()
        if dropped:
            return dropped
        for entry in recent_codes(within_seconds=timeout_s + 120.0):
            if entry["ts"] >= floor - 5:
                return entry["code"]
        time.sleep(poll_s)
    return None
