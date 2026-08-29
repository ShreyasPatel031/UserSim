"""Vertex credentials.

Cloud VMs will not have an interactive gcloud login. Prefer the Searce
authorized-user JSON at secrets/vertex_adc.json (copied from
~/.config/gcloud/legacy_credentials/shreyas.patel@searce.com/adc.json).

Do not use application-default credentials from this laptop: ADC is a
different Google account than shreyas.patel@searce.com.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from config import GCP_ACCOUNT, ROOT

_CLOUD_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

_cached: Credentials | None = None
_expires: datetime | None = None


def _adc_path() -> Path | None:
    raw = [
        str(ROOT / "secrets" / "vertex_adc.json"),
        os.environ.get("VERTEX_ADC"),
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        # gcloud writes an authorized-user JSON (with a refresh token) per account.
        # Preferred over `print-access-token`, whose bare token cannot be refreshed.
        str(
            Path.home()
            / ".config"
            / "gcloud"
            / "legacy_credentials"
            / GCP_ACCOUNT
            / "adc.json"
        ),
    ]
    for item in raw:
        if not item:
            continue
        path = Path(item)
        if not path.is_absolute():
            path = ROOT / path
        if path.is_file():
            return path
    return None


def _from_authorized_user(path: Path) -> Credentials:
    info = json.loads(path.read_text())
    creds = Credentials.from_authorized_user_info(info, scopes=_CLOUD_SCOPES)
    if not creds.valid:
        creds.refresh(Request())
    return creds


def _from_gcloud() -> Credentials:
    token = subprocess.check_output(
        ["gcloud", "auth", "print-access-token", f"--account={GCP_ACCOUNT}"],
        text=True,
    ).strip()
    return Credentials(token=token)


def invalidate_credentials() -> None:
    """Drop the cached token so the next call re-mints one.

    Callers that see 401 UNAUTHENTICATED should invalidate and retry once:
    a bare `gcloud` access token has no refresh handle, so a long-running
    process will otherwise keep replaying a dead token.
    """
    global _cached, _expires
    _cached = None
    _expires = None


def vertex_credentials() -> Credentials:
    global _cached, _expires
    now = datetime.now(timezone.utc)
    if _cached is not None and _expires is not None and now < _expires:
        return _cached

    path = _adc_path()
    if path is not None:
        creds = _from_authorized_user(path)
        # Refresh tokens are long-lived; cache the access token briefly.
        expiry = creds.expiry
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        _cached = creds
        _expires = (expiry - timedelta(minutes=5)) if expiry else now + timedelta(minutes=45)
        return _cached

    # No refresh token available: access tokens live ~1h, so keep the cache well
    # inside that window rather than assuming a run finishes before expiry.
    creds = _from_gcloud()
    _cached = creds
    _expires = now + timedelta(minutes=20)
    return _cached
