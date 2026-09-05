"""Read Google verification codes straight out of Gmail over IMAP.

This breaks the circular challenge where Google emails a code *to the account
being signed into*: with an app password, the code can be read without a
browser session.

Setup (one time, ~1 minute):
  Google Account -> Security -> 2-Step Verification -> App passwords
  Generate one, then add it to secrets/credentials.json as "app_password".

IMAP works with app passwords even when interactive sign-in is challenged.
"""

from __future__ import annotations

import email
import email.utils
import imaplib
import re
import time
from email.header import decode_header
from typing import Any

IMAP_HOST = "imap.gmail.com"

_CODE_RE = re.compile(r"\b(\d{6,8})\b")
_SUBJECT_HINTS = (
    "verification code",
    "verify",
    "security code",
    "sign-in",
    "sign in",
    "google",
)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    out = []
    for part, enc in decode_header(value):
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(part)
    return "".join(out)


def _body_text(msg: email.message.Message) -> str:
    if not msg.is_multipart():
        payload = msg.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")
    chunks = []
    for part in msg.walk():
        if part.get_content_type() in ("text/plain", "text/html"):
            payload = part.get_payload(decode=True) or b""
            chunks.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(chunks)


def imap_ready(username: str, app_password: str | None) -> tuple[bool, str]:
    """Whether IMAP login works with this app password."""
    if not app_password:
        return False, "no app_password in vault"
    try:
        con = imaplib.IMAP4_SSL(IMAP_HOST)
        con.login(username, app_password.replace(" ", ""))
        con.logout()
        return True, "ok"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def latest_code(
    username: str,
    app_password: str,
    *,
    newer_than: float | None = None,
    lookback: int = 15,
) -> str | None:
    """Newest Google verification code found in the mailbox."""
    try:
        con = imaplib.IMAP4_SSL(IMAP_HOST)
        con.login(username, app_password.replace(" ", ""))
    except Exception:
        return None
    try:
        con.select("INBOX")
        typ, data = con.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return None
        ids = data[0].split()[-lookback:]
        for msg_id in reversed(ids):
            typ, raw = con.fetch(msg_id, "(RFC822)")
            if typ != "OK" or not raw or not isinstance(raw[0], tuple):
                continue
            msg = email.message_from_bytes(raw[0][1])
            subject = _decode(msg.get("Subject")).lower()
            sender = _decode(msg.get("From")).lower()
            if "google" not in sender and not any(h in subject for h in _SUBJECT_HINTS):
                continue
            if newer_than is not None:
                try:
                    ts = email.utils.mktime_tz(email.utils.parsedate_tz(msg.get("Date")))
                    if ts < newer_than - 60:
                        continue
                except Exception:
                    pass
            text = f"{subject}\n{_body_text(msg)}"
            match = re.search(r"\bG-(\d{6})\b", text) or _CODE_RE.search(text)
            if match:
                return match.group(1)
        return None
    finally:
        try:
            con.logout()
        except Exception:
            pass


def wait_for_email_code(
    username: str,
    app_password: str,
    *,
    timeout_s: float = 240.0,
    newer_than: float | None = None,
    poll_s: float = 5.0,
) -> str | None:
    started = time.time()
    floor = newer_than if newer_than is not None else started
    while time.time() - started < timeout_s:
        code = latest_code(username, app_password, newer_than=floor)
        if code:
            return code
        time.sleep(poll_s)
    return None


def status(creds: dict[str, Any]) -> dict[str, Any]:
    ok, reason = imap_ready(creds.get("username") or "", creds.get("app_password"))
    return {"imap_ok": ok, "reason": reason}


# ---------------------------------------------------------------------------
# Product signup: match on the To/Delivered-To alias, not Google sender.
# ---------------------------------------------------------------------------

_SIGNUP_HINTS = (
    "verification",
    "verify",
    "confirm",
    "confirmation",
    "activate",
    "activation",
    "security code",
    "one-time",
    "otp",
    "sign up",
    "signup",
    "welcome",
    "magic link",
)
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_SKIP_LINK_HINTS = (
    "unsubscribe",
    "privacy",
    "terms",
    "help.",
    "support.",
    "static.",
    "cdn.",
    "fonts.",
    "facebook.com",
    "twitter.com",
    "linkedin.com",
    "instagram.com",
)


def _imap_creds() -> tuple[str, str] | None:
    """Base Gmail username + app_password from the vault (plus-aliases land here)."""
    from mvp.credentials import _load_vault

    vault = _load_vault()
    for site in vault.get("sites") or []:
        user = (site.get("username") or "").strip()
        app = (site.get("app_password") or "").strip()
        if user and app and "@" in user:
            return user, app
    # Also allow vault-root app_password with any username.
    app = (vault.get("app_password") or "").strip()
    for site in vault.get("sites") or []:
        user = (site.get("username") or "").strip()
        if user and app and "@" in user:
            return user, app
    return None


def _recipients(msg: email.message.Message) -> str:
    parts = [
        _decode(msg.get("To")),
        _decode(msg.get("Delivered-To")),
        _decode(msg.get("X-Original-To")),
        _decode(msg.get("Cc")),
    ]
    return " ".join(p for p in parts if p).lower()


def _msg_timestamp(msg: email.message.Message) -> float | None:
    try:
        return float(email.utils.mktime_tz(email.utils.parsedate_tz(msg.get("Date"))))
    except Exception:
        return None


def _iter_recent_messages(
    username: str,
    app_password: str,
    *,
    lookback: int = 40,
):
    try:
        con = imaplib.IMAP4_SSL(IMAP_HOST)
        con.login(username, app_password.replace(" ", ""))
    except Exception:
        return
    try:
        con.select("INBOX")
        typ, data = con.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return
        ids = data[0].split()[-lookback:]
        for msg_id in reversed(ids):
            typ, raw = con.fetch(msg_id, "(RFC822)")
            if typ != "OK" or not raw or not isinstance(raw[0], tuple):
                continue
            yield email.message_from_bytes(raw[0][1])
    finally:
        try:
            con.logout()
        except Exception:
            pass


def _alias_match(recipients: str, alias: str) -> bool:
    alias = (alias or "").strip().lower()
    if not alias:
        return False
    if alias in recipients:
        return True
    # Gmail sometimes rewrites plus-aliases; also accept local+tag without domain.
    if "+" in alias:
        local = alias.split("@", 1)[0]
        return local in recipients
    return False


def latest_signup_code(
    alias: str,
    *,
    newer_than: float | None = None,
    lookback: int = 40,
) -> str | None:
    """Newest verification code emailed to ``alias`` (any sender)."""
    creds = _imap_creds()
    if not creds:
        return None
    username, app_password = creds
    for msg in _iter_recent_messages(username, app_password, lookback=lookback):
        if not _alias_match(_recipients(msg), alias):
            continue
        if newer_than is not None:
            ts = _msg_timestamp(msg)
            if ts is not None and ts < newer_than - 60:
                continue
        subject = _decode(msg.get("Subject"))
        text = f"{subject}\n{_body_text(msg)}"
        low = text.lower()
        if not any(h in low for h in _SIGNUP_HINTS) and not _CODE_RE.search(text):
            continue
        match = re.search(r"\bG-(\d{6})\b", text) or _CODE_RE.search(text)
        if match:
            return match.group(1)
    return None


def latest_signup_link(
    alias: str,
    *,
    host: str | None = None,
    newer_than: float | None = None,
    lookback: int = 40,
) -> str | None:
    """Newest confirmation / magic link emailed to ``alias``.

    Prefers URLs whose domain contains ``host`` (the product being signed up for).
    """
    creds = _imap_creds()
    if not creds:
        return None
    username, app_password = creds
    host_l = (host or "").lower().lstrip(".")
    if host_l.startswith("www."):
        host_l = host_l[4:]

    for msg in _iter_recent_messages(username, app_password, lookback=lookback):
        if not _alias_match(_recipients(msg), alias):
            continue
        if newer_than is not None:
            ts = _msg_timestamp(msg)
            if ts is not None and ts < newer_than - 60:
                continue
        subject = _decode(msg.get("Subject"))
        text = f"{subject}\n{_body_text(msg)}"
        low = text.lower()
        if not any(h in low for h in _SIGNUP_HINTS) and "http" not in low:
            continue
        candidates: list[str] = []
        preferred: list[str] = []
        for url in _URL_RE.findall(text):
            clean = url.rstrip(").,;\"'>]")
            low_u = clean.lower()
            if any(skip in low_u for skip in _SKIP_LINK_HINTS):
                continue
            candidates.append(clean)
            if host_l and host_l in low_u:
                preferred.append(clean)
        if preferred:
            return preferred[0]
        # Heuristic: prefer links that look like verify/confirm/activate.
        for url in candidates:
            low_u = url.lower()
            if any(k in low_u for k in ("verify", "confirm", "activate", "magic", "token", "invite")):
                return url
        if candidates:
            return candidates[0]
    return None


def wait_for_signup_code(
    alias: str,
    *,
    timeout_s: float = 240.0,
    newer_than: float | None = None,
    poll_s: float = 5.0,
) -> str | None:
    started = time.time()
    floor = newer_than if newer_than is not None else started
    while time.time() - started < timeout_s:
        code = latest_signup_code(alias, newer_than=floor)
        if code:
            return code
        time.sleep(poll_s)
    return None


def wait_for_signup_link(
    alias: str,
    *,
    host: str | None = None,
    timeout_s: float = 240.0,
    newer_than: float | None = None,
    poll_s: float = 5.0,
) -> str | None:
    started = time.time()
    floor = newer_than if newer_than is not None else started
    while time.time() - started < timeout_s:
        link = latest_signup_link(alias, host=host, newer_than=floor)
        if link:
            return link
        time.sleep(poll_s)
    return None
