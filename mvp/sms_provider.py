"""SMS verification backends for product signup.

Backends (selected by ``MVP_SMS_BACKEND``):

- ``messages`` — read codes from the local macOS Messages DB via
  :mod:`mvp.sms_codes`, using the owner's real phone from the vault. Only works
  on the owner's Mac, and only while it is awake.
- ``ntfy`` — read codes the phone itself forwards to an ntfy topic. The owner's
  real number, no Mac in the path, so this is the backend a Linux seed uses.
- ``api`` — lease a disposable number from an HTTP provider (SMS-Activate or
  TextVerified). Used when a product has already burned the real phone number.

The default is platform-aware: ``messages`` on macOS, ``ntfy`` elsewhere when a
topic is configured, because the Messages DB cannot exist on a VM.

Env:
  MVP_SMS_BACKEND=messages|ntfy|api
  MVP_NTFY_SMS_TOPIC=...   # defaults to "<ntfy_topic>-sms" from the vault
  MVP_NTFY_BASE=https://ntfy.sh
  MVP_SMS_API=sms-activate|textverified
  MVP_SMS_API_KEY=...
  MVP_SMS_COUNTRY=0   # SMS-Activate country id (0 = any/RU default — set explicitly)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from mvp.credentials import _load_vault, push_sms_topic
from mvp.email_codes import _CODE_REJECT, _find_code
from mvp.sms_codes import messages_readable, wait_for_code

NTFY_BASE = "https://ntfy.sh"


@dataclass
class Number:
    phone: str
    backend: str
    lease_id: str | None = None
    service: str | None = None
    raw: dict[str, Any] | None = None


def _backend() -> str:
    raw = (os.environ.get("MVP_SMS_BACKEND") or "").strip().lower()
    if raw:
        return raw
    # Defaulting to "messages" off-macOS guarantees a confusing failure deep in a
    # signup run: the Messages DB simply is not there. Prefer the forwarded-SMS
    # path, which is the only one that works unattended on a seed.
    if sys.platform != "darwin" and push_sms_topic():
        return "ntfy"
    return "messages"


def _ntfy_base() -> str:
    return (os.environ.get("MVP_NTFY_BASE") or NTFY_BASE).rstrip("/")


def _ntfy_headers() -> dict[str, str]:
    """Auth for the SMS topic, when configured.

    Real verification codes flow over this topic. On public ntfy.sh an unguessable
    name is the only thing protecting it, so support a token (reserved topic or a
    self-hosted server) and use it whenever one is present.
    """
    token = (
        os.environ.get("MVP_NTFY_TOKEN")
        or ((_load_vault().get("push") or {}).get("ntfy_token") or "")
    ).strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _api_name() -> str:
    return (os.environ.get("MVP_SMS_API") or "sms-activate").strip().lower()


def _api_key() -> str:
    key = (os.environ.get("MVP_SMS_API_KEY") or "").strip()
    if key:
        return key
    vault = _load_vault()
    sms = vault.get("sms") or {}
    return (sms.get("api_key") or "").strip()


def vault_phone() -> str | None:
    vault = _load_vault()
    for site in vault.get("sites") or []:
        phone = (site.get("phone") or "").strip()
        if phone:
            return phone
    owner = vault.get("owner") or {}
    phone = (owner.get("phone") or "").strip()
    return phone or None


def lease_number(service: str = "other") -> Number:
    """Lease (or reuse) a phone number for SMS verification.

    ``service`` is a free-form product hint; SMS-Activate maps common short
    codes (``go`` = Google, ``tg`` = Telegram, etc.). Unknown services fall
    back to the ``ot`` (other) category.
    """
    backend = _backend()
    if backend in {"messages", "local", "macos"}:
        phone = vault_phone()
        if not phone:
            raise RuntimeError(
                "MVP_SMS_BACKEND=messages but no phone in secrets/credentials.json"
            )
        ok, reason = messages_readable()
        if not ok:
            raise RuntimeError(f"Messages DB not readable: {reason}")
        return Number(phone=phone, backend="messages", service=service)

    if backend in {"ntfy", "push", "forward"}:
        phone = vault_phone()
        if not phone:
            raise RuntimeError(
                "MVP_SMS_BACKEND=ntfy but no phone in secrets/credentials.json"
            )
        topic = push_sms_topic()
        if not topic:
            raise RuntimeError(
                "MVP_SMS_BACKEND=ntfy requires MVP_NTFY_SMS_TOPIC or push.ntfy_topic "
                "in secrets/credentials.json"
            )
        # Nothing is leased — this is the owner's own number, forwarded by the
        # handset. The topic is recorded so wait_for_sms knows where to listen.
        return Number(
            phone=phone,
            backend="ntfy",
            service=service,
            raw={"topic": topic},
        )

    if backend != "api":
        raise RuntimeError(f"Unknown MVP_SMS_BACKEND={backend!r}")

    key = _api_key()
    if not key:
        raise RuntimeError("MVP_SMS_BACKEND=api requires MVP_SMS_API_KEY")
    api = _api_name()
    if api in {"sms-activate", "smsactivate", "sms_activate"}:
        return _sms_activate_lease(key, service)
    if api in {"textverified", "text-verified"}:
        return _textverified_lease(key, service)
    raise RuntimeError(f"Unknown MVP_SMS_API={api!r}")


def wait_for_sms(
    number: Number,
    *,
    timeout_s: float = 180.0,
    newer_than: float | None = None,
    poll_s: float = 3.0,
) -> str | None:
    """Block until a verification code arrives for ``number``."""
    if number.backend == "messages":
        return wait_for_code(
            timeout_s=timeout_s,
            newer_than=newer_than,
            poll_s=poll_s,
        )
    if number.backend == "ntfy":
        return _ntfy_wait(
            number,
            timeout_s=timeout_s,
            newer_than=newer_than,
            poll_s=poll_s,
        )
    if number.backend == "sms-activate":
        return _sms_activate_wait(number, timeout_s=timeout_s, poll_s=poll_s)
    if number.backend == "textverified":
        return _textverified_wait(number, timeout_s=timeout_s, poll_s=poll_s)
    raise RuntimeError(f"Unknown SMS backend {number.backend!r}")


# Wording that marks a nearby digit run as the code, looser than the email
# variant: SMS copy is terse and rarely says "verification code" in full.
_SMS_NEAR = re.compile(
    r"(?is)(?:"
    r"(?:code|pin|otp|passcode)\D{0,20}(\d{4,8})"
    r"|(\d{4,8})\D{0,24}(?:to\s+(?:verify|confirm|log\s?in|sign\s?in)|is\s+your)"
    r"|(?:use|enter)\D{0,12}(\d{4,8})"
    r")"
)

# A bare 4-digit run is ambiguous, so exclude the things it is usually not.
_YEARLIKE = re.compile(r"^(?:19|20)\d{2}$")
# Digits introduced as a sender, or glued to a phone number, are not the code.
_SENDER_CTX = re.compile(r"(?i)(?:from|sender|tel|phone)\s*:?\s*\+?$|[+\-()\d]$")


def _sms_code(title: str, body: str) -> str | None:
    """Extract a verification code from a forwarded SMS.

    :func:`mvp.email_codes._find_code` treats its first argument as an email
    subject and scans it before anything else, which is right for mail. A
    forwarded SMS is shaped differently: the notification title carries the
    *sender* — often a 5-6 digit short code that looks exactly like a
    verification code — while the real code is in the body. Feeding the title in
    as a subject reads the short code and silently fails the signup.

    So: body first, then a short-code-aware fallback, and only then the title.
    """
    code = _find_code("", body)
    if code:
        return code

    # The email extractor's last resort needs 6-8 digits; plenty of services
    # send 4- or 5-digit codes over SMS.
    for match in _SMS_NEAR.finditer(body):
        for group in match.groups():
            if group and not _CODE_REJECT.match(group) and not _YEARLIKE.match(group):
                return group

    # An SMS is short plain text, so a lone digit run is very likely the code —
    # unlike an HTML email, where it is as likely to be a tracking id.
    for match in re.finditer(r"\b(\d{4,8})\b", body):
        value = match.group(1)
        if _CODE_REJECT.match(value) or _YEARLIKE.match(value):
            continue
        if _SENDER_CTX.search(body[: match.start()].rstrip()[-12:]):
            continue
        return value

    return _find_code("", f"{title}\n{body}")


def _ntfy_wait(
    number: Number,
    *,
    timeout_s: float,
    newer_than: float | None,
    poll_s: float,
) -> str | None:
    """Read a code the handset forwarded to an ntfy topic.

    ntfy's ``poll=1`` endpoint returns newline-delimited JSON from its cache, so
    this needs no streaming connection and survives the VM losing network for a
    while — a reconnect still sees anything published in the meantime.

    ``newer_than`` matters more here than for a leased number: the topic retains
    prior messages, and reusing a code from an earlier signup silently fails the
    current one. Anything published before the agent asked is ignored.
    """
    topic = (number.raw or {}).get("topic") or push_sms_topic()
    if not topic:
        raise RuntimeError("ntfy SMS backend has no topic")

    cutoff = newer_than or time.time()
    # A couple of seconds of slack for clock skew between handset and VM.
    since = int(cutoff - 5)
    url = f"{_ntfy_base()}/{quote(topic, safe='')}/json"

    deadline = time.monotonic() + timeout_s
    seen: set[str] = set()
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(
                url,
                params={"poll": "1", "since": str(since)},
                headers=_ntfy_headers(),
                timeout=20.0,
            )
            if resp.status_code < 300:
                for line in resp.text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # The stream also carries "open"/"keepalive" control events.
                    if msg.get("event") != "message":
                        continue
                    msg_id = str(msg.get("id") or "")
                    if msg_id in seen:
                        continue
                    seen.add(msg_id)
                    if float(msg.get("time") or 0) < cutoff - 5:
                        continue
                    code = _sms_code(
                        str(msg.get("title") or ""),
                        str(msg.get("message") or ""),
                    )
                    if code:
                        return code
        except Exception:
            # Transient network/DNS blips should not abort a signup mid-flow.
            pass
        time.sleep(poll_s)
    return None


def release(number: Number) -> None:
    """Release a leased number (no-op for owner-phone backends)."""
    if number.backend in {"messages", "ntfy"} or not number.lease_id:
        return
    key = _api_key()
    if not key:
        return
    if number.backend == "sms-activate":
        try:
            httpx.get(
                "https://api.sms-activate.org/stubs/handler_api.php",
                params={"api_key": key, "action": "setStatus", "status": "6", "id": number.lease_id},
                timeout=15.0,
            )
        except Exception:
            pass
    # TextVerified leases typically expire; no explicit release required.


# --- SMS-Activate -----------------------------------------------------------------


_SERVICE_MAP = {
    "google": "go",
    "youtube": "go",
    "gmail": "go",
    "telegram": "tg",
    "whatsapp": "wa",
    "discord": "ds",
    "twitter": "tw",
    "x": "tw",
    "facebook": "fb",
    "instagram": "ig",
    "microsoft": "mm",
    "apple": "wx",
    "other": "ot",
}


def _map_service(service: str) -> str:
    s = (service or "other").strip().lower()
    if len(s) <= 3 and s.isalpha():
        return s
    for key, code in _SERVICE_MAP.items():
        if key in s:
            return code
    return "ot"


def _sms_activate_lease(key: str, service: str) -> Number:
    country = os.environ.get("MVP_SMS_COUNTRY", "0").strip() or "0"
    svc = _map_service(service)
    resp = httpx.get(
        "https://api.sms-activate.org/stubs/handler_api.php",
        params={
            "api_key": key,
            "action": "getNumber",
            "service": svc,
            "country": country,
        },
        timeout=30.0,
    )
    text = (resp.text or "").strip()
    # ACCESS_NUMBER:id:phone
    if not text.startswith("ACCESS_NUMBER:"):
        raise RuntimeError(f"sms-activate getNumber failed: {text[:200]}")
    parts = text.split(":")
    if len(parts) < 3:
        raise RuntimeError(f"sms-activate unexpected response: {text[:200]}")
    lease_id, phone = parts[1], parts[2]
    return Number(
        phone=phone,
        backend="sms-activate",
        lease_id=lease_id,
        service=svc,
        raw={"response": text},
    )


def _sms_activate_wait(
    number: Number,
    *,
    timeout_s: float,
    poll_s: float,
) -> str | None:
    key = _api_key()
    # Mark ready to receive.
    try:
        httpx.get(
            "https://api.sms-activate.org/stubs/handler_api.php",
            params={"api_key": key, "action": "setStatus", "status": "1", "id": number.lease_id},
            timeout=15.0,
        )
    except Exception:
        pass
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            resp = httpx.get(
                "https://api.sms-activate.org/stubs/handler_api.php",
                params={"api_key": key, "action": "getStatus", "id": number.lease_id},
                timeout=15.0,
            )
            text = (resp.text or "").strip()
        except Exception:
            text = ""
        # STATUS_OK:code
        if text.startswith("STATUS_OK:"):
            return text.split(":", 1)[1].strip()
        if text.startswith("STATUS_CANCEL"):
            return None
        time.sleep(poll_s)
    return None


# --- TextVerified -----------------------------------------------------------------


def _textverified_lease(key: str, service: str) -> Number:
    # Minimal REST shape; TextVerified's API evolves — keep env override for base URL.
    base = (os.environ.get("MVP_TEXTVERIFIED_BASE") or "https://www.textverified.com/api").rstrip("/")
    headers = {"Authorization": key, "Content-Type": "application/json"}
    resp = httpx.post(
        f"{base}/Verifications",
        headers=headers,
        json={"id": service or "other"},
        timeout=30.0,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"textverified lease failed: {resp.status_code} {resp.text[:200]}")
    data = resp.json() if resp.content else {}
    phone = str(data.get("number") or data.get("phoneNumber") or "")
    lease_id = str(data.get("id") or data.get("verificationId") or "")
    if not phone or not lease_id:
        raise RuntimeError(f"textverified unexpected payload: {str(data)[:200]}")
    return Number(
        phone=phone,
        backend="textverified",
        lease_id=lease_id,
        service=service,
        raw=data if isinstance(data, dict) else None,
    )


def _textverified_wait(
    number: Number,
    *,
    timeout_s: float,
    poll_s: float,
) -> str | None:
    base = (os.environ.get("MVP_TEXTVERIFIED_BASE") or "https://www.textverified.com/api").rstrip("/")
    key = _api_key()
    headers = {"Authorization": key}
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            resp = httpx.get(
                f"{base}/Verifications/{quote(str(number.lease_id))}",
                headers=headers,
                timeout=15.0,
            )
            data = resp.json() if resp.content else {}
        except Exception:
            data = {}
        code = data.get("sms") or data.get("code") or data.get("verificationCode")
        if code:
            return str(code).strip()
        time.sleep(poll_s)
    return None


def status() -> dict[str, Any]:
    backend = _backend()
    out: dict[str, Any] = {"backend": backend, "vault_phone": bool(vault_phone())}
    if backend in {"messages", "local", "macos"}:
        ok, reason = messages_readable()
        out["messages_ok"] = ok
        out["messages_reason"] = reason
        if sys.platform != "darwin":
            out["messages_reason"] = "not macOS — Messages DB cannot exist here"
    elif backend in {"ntfy", "push", "forward"}:
        topic = push_sms_topic()
        out["ntfy_topic_set"] = bool(topic)
        out["ntfy_base"] = _ntfy_base()
        out["ntfy_authenticated"] = bool(_ntfy_headers())
        if topic:
            # Reachability only. Absence of messages is normal and not an error.
            try:
                resp = httpx.get(
                    f"{_ntfy_base()}/{quote(topic, safe='')}/json",
                    params={"poll": "1", "since": "5m"},
                    headers=_ntfy_headers(),
                    timeout=10.0,
                )
                out["ntfy_reachable"] = resp.status_code < 300
                out["recent_messages"] = sum(
                    1
                    for line in resp.text.splitlines()
                    if line.strip() and '"event":"message"' in line.replace(" ", "")
                )
            except Exception as exc:
                out["ntfy_reachable"] = False
                out["ntfy_error"] = f"{type(exc).__name__}: {exc}"
    else:
        out["api"] = _api_name()
        out["api_key_set"] = bool(_api_key())
    return out
