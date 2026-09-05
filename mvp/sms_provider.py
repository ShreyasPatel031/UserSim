"""SMS verification backends for product signup.

Backends (selected by ``MVP_SMS_BACKEND``):

- ``messages`` (default) — read codes from the local macOS Messages DB via
  :mod:`mvp.sms_codes`, using the owner's real phone from the vault.
- ``api`` — lease a disposable number from an HTTP provider (SMS-Activate or
  TextVerified). Used when a product has already burned the real phone number.

Env:
  MVP_SMS_BACKEND=messages|api
  MVP_SMS_API=sms-activate|textverified
  MVP_SMS_API_KEY=...
  MVP_SMS_COUNTRY=0   # SMS-Activate country id (0 = any/RU default — set explicitly)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from mvp.credentials import _load_vault
from mvp.sms_codes import messages_readable, wait_for_code


@dataclass
class Number:
    phone: str
    backend: str
    lease_id: str | None = None
    service: str | None = None
    raw: dict[str, Any] | None = None


def _backend() -> str:
    return (os.environ.get("MVP_SMS_BACKEND") or "messages").strip().lower()


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
    if number.backend == "sms-activate":
        return _sms_activate_wait(number, timeout_s=timeout_s, poll_s=poll_s)
    if number.backend == "textverified":
        return _textverified_wait(number, timeout_s=timeout_s, poll_s=poll_s)
    raise RuntimeError(f"Unknown SMS backend {number.backend!r}")


def release(number: Number) -> None:
    """Release a leased number (no-op for the Messages backend)."""
    if number.backend == "messages" or not number.lease_id:
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
    else:
        out["api"] = _api_name()
        out["api_key_set"] = bool(_api_key())
    return out
