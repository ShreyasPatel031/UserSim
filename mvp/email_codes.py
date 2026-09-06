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
from html import unescape
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


def _strip_html(raw: str) -> str:
    """Drop markup so digits inside tags/URLs are not mistaken for codes."""
    out = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", raw)
    out = re.sub(r"(?i)<br\s*/?>|</(p|div|td|tr|h[1-6])>", "\n", out)
    out = re.sub(r"(?s)<[^>]+>", " ", out)
    out = unescape(out)
    out = re.sub(r"[ \t\xa0]+", " ", out)
    return re.sub(r"\n{2,}", "\n", out)


def _body_text(msg: email.message.Message) -> str:
    """Readable text of the message, preferring text/plain over HTML."""
    if not msg.is_multipart():
        payload = msg.get_payload(decode=True) or b""
        text = payload.decode("utf-8", errors="replace")
        return _strip_html(text) if msg.get_content_type() == "text/html" else text

    plain: list[str] = []
    html: list[str] = []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True) or b""
        text = payload.decode("utf-8", errors="replace")
        (plain if ctype == "text/plain" else html).append(text)
    # text/plain first: the HTML alternative carries tracking ids and inline
    # styles whose digits look exactly like a 6-digit code.
    if plain:
        return "\n".join(plain)
    return _strip_html("\n".join(html))


# Placeholders and obviously-not-a-code runs seen in real signup mail.
_CODE_REJECT = re.compile(r"^(\d)\1+$|^(?:012345|123456|654321|999999|000000)\d*$")
_CODE_NEAR = re.compile(
    r"(?is)(?:"
    r"(?:verification|security|confirmation|one[- ]time|login|sign[- ]?in|temporary)\s+code[^0-9A-Za-z]{0,40}([0-9A-Za-z]{4,8})"
    r"|code\s*(?:is|:)\s*([0-9A-Za-z]{4,8})"
    r"|([0-9A-Za-z]{4,8})\s*(?:is\s+your|is\s+the)\b"
    r"|enter\s+(?:this\s+)?(?:code\s*)?[^0-9A-Za-z]{0,20}([0-9A-Za-z]{4,8})"
    r")"
)
# Notion (and some others) now send alphanumeric OTPs on their own line, e.g. "ND4wwu".
_ALNUM_LINE = re.compile(r"(?m)^[ \t]*([A-Za-z0-9]{6,8})[ \t]*$")
_ALNUM_REJECT = re.compile(
    r"(?i)^(password|username|notion|welcome|verify|confirm|account|message)$"
)


def _find_code(subject: str, body: str) -> str | None:
    """Best-effort verification code from one message.

    A bare "first 6-8 digits" scan picks up tracking ids and CSS values; loom
    signup failed on a code of "999999" lifted out of the HTML part. Notion
    also ships alphanumeric login codes (``ND4wwu``) — accept those when they
    sit alone on a line or next to code-ish wording.
    """
    subject = subject or ""
    body = body or ""

    google = re.search(r"\bG-(\d{6})\b", f"{subject}\n{body}")
    if google:
        return google.group(1)

    def _ok(value: str | None) -> str | None:
        if value and not _CODE_REJECT.match(value):
            return value
        return None

    def _ok_alnum(value: str | None) -> str | None:
        if not value:
            return None
        if _ALNUM_REJECT.match(value):
            return None
        # Prefer mixed / non-trivial tokens; pure words rejected above.
        if value.isalpha() and value.lower() == value and len(value) >= 6:
            # all-lowercase alpha often a normal word; require a digit OR uppercase
            return None
        return value

    # 0) Lone alphanumeric OTP line (Notion temporary login codes).
    for match in _ALNUM_LINE.finditer(body.replace("\r\n", "\n")):
        cand = _ok_alnum(match.group(1))
        if cand:
            return cand

    # 1) Subject lines usually read "123456 is your code".
    for cand in re.findall(r"\b(\d{4,8})\b", subject):
        if _ok(cand):
            return cand

    # 2) Digits / alnum sitting next to code-ish wording.
    for match in _CODE_NEAR.finditer(f"{subject}\n{body}"):
        for group in match.groups():
            if group and group.isdigit():
                if _ok(group):
                    return group
            else:
                cand = _ok_alnum(group)
                if cand:
                    return cand

    # 3) A line that is nothing but the code.
    for line in body.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"\d{4,8}", stripped) and _ok(stripped):
            return stripped

    # 4) Last resort: any standalone 6-8 digit run.
    for cand in re.findall(r"\b(\d{6,8})\b", body):
        if _ok(cand):
            return cand
    return None


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
            code = _find_code(subject, _body_text(msg))
            if code:
                return code
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
    "login code",
    "temporary",
    "your code",
    "bitwarden",
    "master password",
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
    "/download",
    "/pricing",
    "/blog",
    "/help/",
    "mailto:",
)


def _imap_creds() -> tuple[str, str] | None:
    """Base Gmail username + app_password.

    Prefer env (cloud-agent secrets), then ``secrets/credentials.json``.
    Plus-aliases all land in the same inbox.
    """
    import os

    env_user = (os.environ.get("GMAIL_USER") or os.environ.get("MVP_GMAIL_USER") or "").strip()
    env_app = (
        os.environ.get("GMAIL_APP_PASSWORD")
        or os.environ.get("MVP_GMAIL_APP_PASSWORD")
        or ""
    ).strip()
    if env_user and env_app and "@" in env_user:
        return env_user, env_app

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
    # Env password + vault username (or vice versa).
    if env_app:
        for site in vault.get("sites") or []:
            user = (site.get("username") or "").strip()
            if user and "@" in user:
                return user, env_app
    if env_user and "@" in env_user:
        for site in vault.get("sites") or []:
            app = (site.get("app_password") or "").strip()
            if app:
                return env_user, app
        app = (vault.get("app_password") or "").strip()
        if app:
            return env_user, app
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
    lookback: int = 80,
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
        body = _body_text(msg)
        low = f"{subject}\n{body}".lower()
        if not any(h in low for h in _SIGNUP_HINTS) and not _CODE_RE.search(low) and not _ALNUM_LINE.search(body):
            continue
        code = _find_code(subject, body)
        if code:
            return code
    return None


def latest_signup_link(
    alias: str,
    *,
    host: str | None = None,
    newer_than: float | None = None,
    lookback: int = 80,
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
    # Product marketing host vs app/vault host (Bitwarden, etc.).
    host_needles = {host_l} if host_l else set()
    if host_l == "bitwarden.com":
        host_needles.update({"bitwarden.com", "vault.bitwarden.com"})
    if host_l.endswith(".bitwarden.com"):
        host_needles.add("bitwarden.com")

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
        verify_keys = ("verify", "confirm", "activate", "magic", "token", "invite", "finish-signup", "email-verification")
        for url in _URL_RE.findall(text):
            clean = url.rstrip(").,;\"'>]")
            low_u = clean.lower()
            if any(skip in low_u for skip in _SKIP_LINK_HINTS):
                continue
            candidates.append(clean)
            if host_needles and any(h in low_u for h in host_needles):
                preferred.append(clean)
        def _verifyish(urls: list[str]) -> str | None:
            for url in urls:
                low_u = url.lower()
                if any(k in low_u for k in verify_keys):
                    return url
            return None
        # Prefer verify/finish-signup even among host matches (Welcome mail
        # often has bitwarden.com/download which would otherwise win).
        hit = _verifyish(preferred) or _verifyish(candidates)
        if hit:
            return hit
        if preferred:
            return preferred[0]
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
    if _imap_creds() is None:
        # Fail fast — hanging 180s+ with no app_password just burns the agent budget.
        raise RuntimeError(
            "No Gmail app_password in secrets/credentials.json — cannot read signup codes"
        )
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
    """Poll for a fresh link; after half the timeout, also accept recent prior mail.

    Retries (Bitwarden) often re-hit an already-sent verify link. Requiring
    ``newer_than=mark_email_requested`` then times out forever even though a
    valid finish-signup URL is sitting in the inbox from the prior attempt.
    """
    if _imap_creds() is None:
        raise RuntimeError(
            "No Gmail app_password in secrets/credentials.json — cannot read signup links"
        )
    started = time.time()
    floor = newer_than if newer_than is not None else started
    fallback_after = started + max(20.0, timeout_s * 0.45)
    # 48h lookback for prior verify/finish links on the same alias.
    prior_floor = time.time() - 48 * 3600
    while time.time() - started < timeout_s:
        link = latest_signup_link(alias, host=host, newer_than=floor)
        if link:
            return link
        if time.time() >= fallback_after:
            link = latest_signup_link(alias, host=host, newer_than=prior_floor)
            if link:
                return link
        time.sleep(poll_s)
    return None
