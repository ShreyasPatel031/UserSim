"""Credential vault for agent sign-ins.

Credentials live in ``secrets/credentials.json`` (gitignored) so they never
reach the repo. Shape:

    {
      "push": {"ntfy_topic": "usersim-shreyas-xxxx"},
      "sites": [
        {
          "match": ["google.com", "youtube.com", "gmail.com"],
          "username": "you@gmail.com",
          "password": "...",
          "phone": "3175550123",
          "totp_secret": null
        }
      ]
    }

``totp_secret`` is the base32 string from Google's "Authenticator app" setup.
When present, sign-in is fully autonomous; otherwise 2FA needs an SMS code
(read from Messages) or a tap on the phone.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "secrets"
VAULT = SECRETS / "credentials.json"


def _load_vault() -> dict[str, Any]:
    if not VAULT.is_file():
        return {}
    try:
        data = json.loads(VAULT.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def credentials_for_url(url: str) -> dict[str, Any] | None:
    """Return the vault entry whose ``match`` list covers this URL's host."""
    host = (urlparse(url).hostname or url or "").lower()
    if not host:
        return None
    for site in _load_vault().get("sites") or []:
        for pattern in site.get("match") or []:
            if pattern.lower() in host:
                return site
    return None


def totp_code(secret: str | None) -> str | None:
    """Current 6-digit code for a base32 TOTP secret."""
    if not secret:
        return None
    try:
        import pyotp
    except ImportError:
        return None
    try:
        return pyotp.TOTP(secret.replace(" ", "")).now()
    except Exception:
        return None


def push_topic() -> str | None:
    """ntfy.sh topic used to ping the owner's phone for manual approvals."""
    return os.environ.get("MVP_NTFY_TOPIC") or (_load_vault().get("push") or {}).get(
        "ntfy_topic"
    )


def vault_status() -> dict[str, Any]:
    """Non-secret summary, safe to log."""
    vault = _load_vault()
    sites = vault.get("sites") or []
    return {
        "vault_exists": VAULT.is_file(),
        "site_count": len(sites),
        "entries": [
            {
                "match": s.get("match"),
                "has_username": bool(s.get("username")),
                "has_password": bool(s.get("password")),
                "has_phone": bool(s.get("phone")),
                "has_totp": bool(s.get("totp_secret")),
            }
            for s in sites
        ],
        "push_topic_set": bool(push_topic()),
    }
