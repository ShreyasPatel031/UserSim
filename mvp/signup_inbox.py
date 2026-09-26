"""Fresh inboxes for in-run signup.

Each signup gets a never-reused address and a way to read the verification
code or magic link sent to it.

Backends, in order:
  * ``gmail``  -- Gmail plus/dotted alias of the vault base address, read over
                  IMAP (same scheme as ``mvp.identity`` / ``mvp.email_codes``).
                  Used when a Gmail app password is available.
  * ``mailtm`` -- a throwaway mailbox on the public mail.tm API (mail.gw as a
                  fallback). Used when no Gmail app password is on the machine.

``MVP_SIGNUP_INBOX=gmail|mailtm`` forces one.
"""

from __future__ import annotations

import os
import re
import secrets
import string
import time
from html import unescape
from typing import Any

import httpx

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_SKIP_LINK = (
    "unsubscribe", "privacy", "terms", "help", "support", "facebook.com", "twitter.com",
    "x.com/", "linkedin.com", "instagram.com", "youtube.com", "apps.apple.com",
    "play.google.com", "/legal", "preferences", "cdn.", ".png", ".jpg", ".gif", "mailto:",
    "tiktok.com", "status.", "/blog", "careers",
)
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
        if clean in seen or any(s in low for s in _SKIP_LINK):
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
            for msg in msgs:
                key = str(msg.get("id") or msg.get("subject"))
                if key in seen:
                    continue
                seen.add(key)
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


_DOMAIN_CACHE: dict[str, tuple[str, float]] = {}


class MailTmInbox(Inbox):
    """Throwaway mailbox on the mail.tm API (or mail.gw, same API)."""

    backend = "mailtm"

    def _req(self, method: str, path: str, **kw: Any) -> httpx.Response:
        """mail.tm rate-limits (429, sometimes an HTML body). Back off and retry."""
        last: httpx.Response | None = None
        for attempt in range(8):
            r = self.client.request(method, f"{self.base}{path}", **kw)
            if r.status_code != 429 and "json" in (r.headers.get("content-type") or "") or r.status_code in (201, 204):
                return r
            last = r
            try:
                wait = float(r.headers.get("retry-after") or 0)
            except ValueError:
                wait = 0.0
            time.sleep(min(10.0, max(wait, 1.0 + attempt * 1.5)))
        assert last is not None
        return last

    def __init__(self, base: str = "https://api.mail.tm", tag: str = "") -> None:
        self.base = base.rstrip("/")
        self.client = httpx.Client(timeout=20.0)
        self._cache: dict[str, dict[str, Any]] = {}
        cached = _DOMAIN_CACHE.get(self.base)
        if cached and time.time() - cached[1] < 600:
            domain = cached[0]
        else:
            doms = self._req("GET", "/domains").json()
            members = doms.get("hydra:member") if isinstance(doms, dict) else doms
            domain = next(d["domain"] for d in members if d.get("isActive", True))
            _DOMAIN_CACHE[self.base] = (domain, time.time())
        local = (re.sub(r"[^a-z0-9]", "", tag.lower())[:10] or "user") + _rand(6)
        self.address = f"{local}@{domain}"
        self.password = _rand(16, string.ascii_letters + string.digits)
        r = self._req("POST", "/accounts", json={"address": self.address, "password": self.password})
        if r.status_code >= 300:
            raise RuntimeError(f"mail.tm account create {r.status_code}: {r.text[:200]}")
        t = self._req("POST", "/token", json={"address": self.address, "password": self.password})
        t.raise_for_status()
        self.client.headers["Authorization"] = f"Bearer {t.json()['token']}"

    def messages(self, newer_than: float) -> list[dict[str, Any]]:
        r = self._req("GET", "/messages")
        if r.status_code >= 300:
            return []
        data = r.json()
        items = data.get("hydra:member") if isinstance(data, dict) else data
        out = []
        for item in items or []:
            if item["id"] in self._cache:
                out.append(self._cache[item["id"]])
                continue
            full = self._req("GET", f"/messages/{item['id']}").json()
            html = full.get("html") or []
            html = "\n".join(html) if isinstance(html, list) else str(html or "")
            text = full.get("text") or _strip_html(html)
            links = _links_from_html(html) + _URL_RE.findall(text or "")
            row = {
                "anchors": anchors_from_html(html),
                "id": item["id"],
                "subject": full.get("subject") or "",
                "sender": ((full.get("from") or {}).get("address") or ""),
                "text": text,
                "links": links,
            }
            self._cache[item["id"]] = row
            out.append(row)
        return out


class GuerrillaInbox(Inbox):
    """Throwaway mailbox on the Guerrilla Mail API (different domains than mail.tm)."""

    backend = "guerrilla"
    API = "https://api.guerrillamail.com/ajax.php"

    def __init__(self, tag: str = "") -> None:
        self.client = httpx.Client(timeout=20.0, headers={"User-Agent": "Mozilla/5.0"})
        r = self.client.get(self.API, params={"f": "get_email_address", "lang": "en"}).json()
        self.sid = r["sid_token"]
        user = (re.sub(r"[^a-z0-9]", "", tag.lower())[:10] or "user") + _rand(6)
        r = self.client.get(self.API, params={"f": "set_email_user", "email_user": user, "sid_token": self.sid}).json()
        self.sid = r.get("sid_token") or self.sid
        domain = os.environ.get("MVP_SIGNUP_GUERRILLA_DOMAIN", "").strip()
        addr = r["email_addr"]
        self.address = f"{addr.split('@')[0]}@{domain}" if domain else addr
        self._cache: dict[str, dict[str, Any]] = {}

    def messages(self, newer_than: float) -> list[dict[str, Any]]:
        r = self.client.get(self.API, params={"f": "check_email", "seq": 0, "sid_token": self.sid}).json()
        out = []
        for item in r.get("list") or []:
            mid = str(item.get("mail_id"))
            if "guerrillamail" in str(item.get("mail_from", "")).lower():
                continue  # welcome mail
            if mid in self._cache:
                out.append(self._cache[mid])
                continue
            full = self.client.get(self.API, params={"f": "fetch_email", "email_id": mid, "sid_token": self.sid}).json()
            html = str(full.get("mail_body") or "")
            text = _strip_html(html)
            row = {
                "id": mid, "subject": full.get("mail_subject") or "", "sender": full.get("mail_from") or "",
                "text": text, "links": _links_from_html(html) + _URL_RE.findall(text),
                "anchors": anchors_from_html(html),
            }
            self._cache[mid] = row
            out.append(row)
        return out


class GmailAliasInbox(Inbox):
    """Plus/dotted alias of the vault Gmail, read over IMAP."""

    backend = "gmail"

    def __init__(self, host: str, tag: str, dotted: bool = False) -> None:
        from mvp.email_codes import _imap_creds
        from mvp.identity import email_for_host

        creds = _imap_creds()
        if not creds:
            raise RuntimeError("no Gmail app password")
        self.username, self.app_password = creds
        self.address = email_for_host(self.username, host, tag=tag, force_dotted=dotted)

    def messages(self, newer_than: float) -> list[dict[str, Any]]:
        from mvp.email_codes import (
            _alias_match,
            _body_text,
            _decode,
            _iter_recent_messages,
            _msg_timestamp,
            _recipients,
        )

        out = []
        for msg in _iter_recent_messages(self.username, self.app_password, lookback=30):
            if not _alias_match(_recipients(msg), self.address):
                continue
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
    """Fresh inbox for one signup attempt."""
    forced = (os.environ.get("MVP_SIGNUP_INBOX") or "").strip().lower()
    if forced not in {"mailtm", "guerrilla"} and (forced == "gmail" or gmail_available()):
        return GmailAliasInbox(host, tag, dotted=dotted)
    last: Exception | None = None
    if forced == "guerrilla":
        return GuerrillaInbox(tag=tag)
    for base in ("https://api.mail.tm", "https://api.mail.gw"):
        try:
            return MailTmInbox(base, tag=tag)
        except Exception as exc:  # noqa: BLE001
            last = exc
    try:
        return GuerrillaInbox(tag=tag)
    except Exception as exc:  # noqa: BLE001
        last = exc
    raise RuntimeError(f"no inbox backend: {last!r}")
