"""Fresh inboxes for in-run signup.

Each signup gets a never-reused address and a way to read the verification
code or magic link sent to it.

The only backend is ``gmail``: a Gmail plus-alias of GMAIL_USER with a random
suffix per signup (``usersim.signups+notion3fa9c1@gmail.com``), read over IMAP with
GMAIL_APP_PASSWORD (same scheme as ``mvp.identity`` / ``mvp.email_codes``).

Throwaway inboxes (mail.tm, mail.gw, Guerrilla Mail) are not used: most
products block their domains (ClickUp DOM_001, Notion, Trello, Calendly), and
the user asked that they never be used. If Gmail credentials are missing,
``create_inbox`` raises ``GmailInboxMissing``; it never falls back.
"""

from __future__ import annotations

import os
import re
import secrets
import string
import time
from html import unescape
from typing import Any

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_SKIP_LINK = (
    "unsubscribe", "privacy", "terms", "help", "support",
    "/legal", "preferences", ".png", ".jpg", ".gif", "mailto:", "/blog", "careers",
)
# Matched against the link's host only: as substrings they also hit real product links
# ("x.com/" is inside "sendfox.com/...", which dropped SendFox's verify link).
_SKIP_HOSTS = (
    "facebook.com", "twitter.com", "x.com", "linkedin.com", "instagram.com", "youtube.com",
    "apps.apple.com", "play.google.com", "tiktok.com",
)
_SKIP_HOST_PREFIX = ("cdn.", "status.")


def _skip_link(url: str) -> bool:
    from urllib.parse import urlsplit

    low = url.lower()
    try:
        host = (urlsplit(low).hostname or "").removeprefix("www.")
    except ValueError:
        return True
    if any(host == d or host.endswith("." + d) for d in _SKIP_HOSTS) or host.startswith(_SKIP_HOST_PREFIX):
        return True
    return any(s in low for s in _SKIP_LINK)
_GOOD_LINK = ("verify", "confirm", "activate", "magic", "token", "login", "signin", "sign-in",
              "auth", "invite", "validate", "email", "onboard", "code", "welcome", "callback")


def _strip_html(raw: str) -> str:
    out = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", raw or "")
    out = re.sub(r"(?i)<br\s*/?>|</(p|div|td|tr|h[1-6])>", "\n", out)
    out = re.sub(r"(?s)<[^>]+>", " ", out)
    out = unescape(out)
    out = re.sub(r"[ \t\xa0]+", " ", out)
    return re.sub(r"\n{2,}", "\n", out)


def _links_from_html(html: str) -> list[str]:
    hrefs = re.findall(r"""href\s*=\s*["']([^"']+)["']""", html or "", re.I)
    return [unescape(h) for h in hrefs if h.lower().startswith("http")]


def anchors_from_html(html: str) -> dict[str, str]:
    """href -> visible anchor text (for picking the right button in an email)."""
    out: dict[str, str] = {}
    for href, inner in re.findall(r"""<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", html or "", re.I | re.S):
        text = re.sub(r"\s+", " ", _strip_html(inner)).strip()
        if href.lower().startswith("http") and text:
            out.setdefault(unescape(href), text[:60])
    return out


def rank_links(links: list[str], host: str) -> list[str]:
    """Verification-looking links first, product-domain links next, junk dropped."""
    host_tok = (host or "").lower().removeprefix("www.").split(".")[0]
    seen: set[str] = set()
    scored: list[tuple[int, int, str]] = []
    for idx, url in enumerate(links):
        clean = url.rstrip(").,;\"'>]")
        low = clean.lower()
        if clean in seen or _skip_link(clean):
            continue
        seen.add(clean)
        score = 0
        if any(k in low for k in _GOOD_LINK):
            score += 3
        if host_tok and host_tok in low:
            score += 2
        if len(clean) > 60:  # tokens are long
            score += 1
        scored.append((-score, idx, clean))
    scored.sort()
    return [u for _, _, u in scored]


_VERIFY_LINK_RE = re.compile(
    r"verif|confirm|activat|magic|oobcode|/auth|token=|sign-?in|log-?in|validate|callback|/v/|otp", re.I)
_VERIFY_SUBJECT_RE = re.compile(
    r"verif|confirm|activat|one click away|magic|sign.?in|log.?in|code|validate|complete your", re.I)


def verification_link(url: str) -> bool:
    """A link that plausibly verifies the account (not a help / welcome / tracking link)."""
    return bool(_VERIFY_LINK_RE.search(url or ""))


def _verify_score(msg: dict[str, Any], host: str) -> int:
    score = 0
    if find_code(msg.get("subject", ""), msg.get("text", "")):
        score += 2
    if any(verification_link(u) for u in rank_links(msg.get("links") or [], host)[:8]):
        score += 2
    if _VERIFY_SUBJECT_RE.search(msg.get("subject") or ""):
        score += 1
    return score


def find_code(subject: str, body: str) -> str | None:
    from mvp.email_codes import _find_code

    return _find_code(subject or "", body or "")


def _rand(n: int, alphabet: str = string.ascii_lowercase + string.digits) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(n))


class Inbox:
    backend = "base"
    address = ""

    def messages(self, newer_than: float) -> list[dict[str, Any]]:
        """[{subject, sender, text, links, ts}] newest first."""
        raise NotImplementedError

    def wait(self, host: str, newer_than: float, timeout_s: float, seen: set[str] | None = None) -> dict[str, Any] | None:
        """Wait for the next unseen message. Returns {subject, code, links, text}."""
        seen = seen if seen is not None else set()
        deadline = time.time() + max(1.0, timeout_s)
        while time.time() < deadline:
            try:
                msgs = self.messages(newer_than)
            except Exception as exc:  # noqa: BLE001
                print(f"[signup_inbox] {self.backend} read failed: {exc!r}", flush=True)
                msgs = []
            fresh = [m for m in msgs if str(m.get("id") or m.get("subject")) not in seen]
            if fresh:
                # the verification mail first (a welcome mail often lands right after it), then the oldest
                fresh.sort(key=lambda m: (-_verify_score(m, host), m.get("ts") or 0))
                msg = fresh[0]
                seen.add(str(msg.get("id") or msg.get("subject")))
                code = find_code(msg.get("subject", ""), msg.get("text", ""))
                anchors = msg.get("anchors") or {}
                ranked = rank_links(msg.get("links") or [], host)[:8]
                return {
                    "subject": msg.get("subject", ""),
                    "sender": msg.get("sender", ""),
                    "code": code,
                    "links": ranked,
                    "link_texts": [anchors.get(u, "") for u in ranked],
                    "text": (msg.get("text") or "")[:3000],
                }
            time.sleep(2.5)
        return None


GMAIL_MISSING_MSG = (
    "Gmail signup inbox missing: set GMAIL_USER and GMAIL_APP_PASSWORD "
    "(throwaway inboxes are disabled)"
)


class GmailInboxMissing(RuntimeError):
    """GMAIL_USER / GMAIL_APP_PASSWORD are required for every in-run signup."""


_USED_LOCK = __import__("threading").Lock()
_USED_FILE = os.path.expanduser(os.environ.get("MVP_GMAIL_VARIANTS_FILE") or "~/.cache/usersim/gmail_variants_used.txt")


def _used_variants(host: str) -> set[str]:
    try:
        with open(_USED_FILE, encoding="utf-8") as fh:
            return {line.split(" ", 1)[1].strip() for line in fh if line.startswith(host + " ")}
    except OSError:
        return set()


def _remember_variant(host: str, local: str) -> None:
    try:
        os.makedirs(os.path.dirname(_USED_FILE), exist_ok=True)
        with open(_USED_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"{host} {local}\n")
    except OSError:
        pass


def _host_list(name: str) -> set[str]:
    return {h.strip().lower().removeprefix("www.") for h in (os.environ.get(name) or "").split(",") if h.strip()}


def fresh_gmail_address(username: str, host: str, tag: str, *, dotted: bool = False) -> str:
    """A never-reused address that still lands in ``username``'s Gmail inbox.

    ``usersim.signups+zo3fa9c1@gmail.com`` alone was not enough: zo.computer treats
    every plus-alias as one address and throttled its mails (study 390909cf got
    2 mails for 18 signups). Each signup now also gets its own dot placement
    (``shr.eya.shfs+zo3fa9c1@gmail.com``) that this host has not seen before,
    so a site that strips ``+tag`` still sees a different address. Hosts that
    reject ``+`` (``dotted``) get the dot variant only. Hosts listed in
    MVP_SIGNUP_GOOGLEMAIL_HOSTS get the @googlemail.com spelling as well.
    MVP_SIGNUP_EMAIL_DOTS=0 turns the dots off.
    """
    from mvp.identity import GMAIL_DOMAINS, gmail_dot_variant

    local, domain = username.rsplit("@", 1)
    local = local.split("+", 1)[0]
    site = (host or "").lower().removeprefix("www.")
    base_tag = re.sub(r"[^a-z0-9]", "", (tag or site.split(".")[0]).lower())[:12] or "signup"
    fresh = base_tag + secrets.token_hex(3)
    dots = os.environ.get("MVP_SIGNUP_EMAIL_DOTS", "1").lower() not in {"0", "false", "no"}
    if domain.lower() in GMAIL_DOMAINS and (dots or dotted):
        with _USED_LOCK:
            used = _used_variants(site)
            local = gmail_dot_variant(local, avoid=used)
            _remember_variant(site, local)
        if site in _host_list("MVP_SIGNUP_GOOGLEMAIL_HOSTS"):
            domain = "googlemail.com"
    if dotted:
        return f"{local}@{domain}"
    return f"{local}+{fresh}@{domain}"


class GmailAliasInbox(Inbox):
    """Plus/dotted alias of the vault Gmail, read over IMAP."""

    backend = "gmail"

    def __init__(self, host: str, tag: str, dotted: bool = False) -> None:
        from mvp.email_codes import _imap_creds

        creds = _imap_creds()
        if not creds:
            raise GmailInboxMissing(GMAIL_MISSING_MSG)
        self.username, self.app_password = creds
        self.address = fresh_gmail_address(self.username, host, tag, dotted=dotted)

    def messages(self, newer_than: float) -> list[dict[str, Any]]:
        from mvp.email_codes import _body_text, _decode, _msg_timestamp, messages_for_alias

        out = []
        try:
            found = messages_for_alias(self.username, self.app_password, self.address, newer_than=newer_than)
        except Exception as exc:  # noqa: BLE001
            print(f"[signup_inbox] gmail poll failed: {exc!r}", flush=True)
            found = []
        for msg in found:
            ts = _msg_timestamp(msg)
            if ts is not None and ts < newer_than - 30:
                continue
            html_parts = []
            for part in msg.walk() if msg.is_multipart() else [msg]:
                if part.get_content_type() == "text/html":
                    html_parts.append((part.get_payload(decode=True) or b"").decode("utf-8", "replace"))
            text = _body_text(msg)
            out.append(
                {
                    "id": msg.get("Message-ID") or _decode(msg.get("Subject")),
                    "subject": _decode(msg.get("Subject")),
                    "sender": _decode(msg.get("From")),
                    "text": text,
                    "links": _links_from_html("\n".join(html_parts)) + _URL_RE.findall(text),
                    "anchors": anchors_from_html("\n".join(html_parts)),
                    "ts": ts,
                }
            )
        return out


def gmail_available() -> bool:
    try:
        from mvp.email_codes import _imap_creds

        return bool(_imap_creds())
    except Exception:
        return False


def create_inbox(host: str, tag: str, *, dotted: bool = False) -> Inbox:
    """Fresh Gmail plus-alias inbox for one signup attempt. Gmail only.

    Raises ``GmailInboxMissing`` when Gmail credentials are absent (or when
    MVP_SIGNUP_INBOX asks for anything other than gmail). No throwaway fallback.
    """
    forced = (os.environ.get("MVP_SIGNUP_INBOX") or "").strip().lower()
    if forced and forced != "gmail":
        raise GmailInboxMissing(
            f"MVP_SIGNUP_INBOX={forced!r} is not supported: signup uses Gmail plus-aliases only"
        )
    if not gmail_available():
        print(f"[signup_inbox] ERROR {GMAIL_MISSING_MSG}", flush=True)
        raise GmailInboxMissing(GMAIL_MISSING_MSG)
    return GmailAliasInbox(host, tag, dotted=dotted)
