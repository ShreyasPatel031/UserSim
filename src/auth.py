"""Vertex credentials.

Cloud VMs will not have an interactive gcloud login. Prefer the Searce
authorized-user JSON at secrets/vertex_adc.json (copied from
~/.config/gcloud/legacy_credentials/shreyas.patel@searce.com/adc.json).

Do not use application-default credentials from this laptop: ADC is a
different Google account than shreyas.patel@searce.com.

On Vercel / serverless, set VERTEX_ADC_JSON (or GOOGLE_ADC_JSON) to the
service-account JSON string — it is written to /tmp and used as ADC.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from config import GCP_ACCOUNT, ROOT

_CLOUD_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

_cached: Credentials | None = None
_expires: datetime | None = None
_materialized_adc: Path | None = None


def _materialize_adc_from_env() -> Path | None:
    """Write VERTEX_ADC_JSON / GOOGLE_ADC_JSON / *_B64 to /tmp once per process."""
    global _materialized_adc
    if _materialized_adc is not None and _materialized_adc.is_file():
        return _materialized_adc
    raw = (
        os.environ.get("VERTEX_ADC_JSON")
        or os.environ.get("GOOGLE_ADC_JSON")
        or os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        or ""
    ).strip()
    if not raw:
        b64 = (
            os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_B64")
            or os.environ.get("VERTEX_ADC_JSON_B64")
            or ""
        ).strip()
        if b64:
            import base64

            try:
                raw = base64.b64decode(b64).decode("utf-8")
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS_B64 is not valid base64") from exc
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("VERTEX_ADC_JSON is not valid JSON") from exc
    if not isinstance(info, dict) or not info.get("type"):
        raise RuntimeError("VERTEX_ADC_JSON must be a credentials object with type")
    fd, name = tempfile.mkstemp(prefix="usersim-adc-", suffix=".json")
    os.close(fd)
    path = Path(name)
    path.write_text(json.dumps(info), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    _materialized_adc = path
    # So google clients / child libs that read the env path also work.
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(path))
    os.environ.setdefault("VERTEX_ADC", str(path))
    return path


def _adc_path() -> Path | None:
    materialized = _materialize_adc_from_env()
    raw = [
        # Env wins: a stale secrets/vertex_adc.json must not shadow the
        # service account an operator explicitly points at.
        os.environ.get("VERTEX_ADC"),
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        str(materialized) if materialized else None,
        str(ROOT / "secrets" / "sa.json"),
        str(ROOT / "secrets" / "vertex_adc.json"),
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


def _from_service_account(path: Path):
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_file(
        str(path), scopes=_CLOUD_SCOPES
    )


def _from_credentials_file(path: Path):
    info = json.loads(path.read_text())
    ctype = (info.get("type") or "").strip()
    if ctype == "service_account":
        return _from_service_account(path)
    if ctype == "authorized_user":
        return _from_authorized_user(path)
    raise RuntimeError(f"Unsupported credentials type {ctype!r} in {path}")


def _from_gcloud() -> Credentials:
    token = subprocess.check_output(
        ["gcloud", "auth", "print-access-token", f"--account={GCP_ACCOUNT}"],
        text=True,
    ).strip()
    return Credentials(token=token)


def _from_application_default():
    """Instance service account / ambient ADC.

    Fleet VMs have no key file and no gcloud login — the metadata server is the
    only credential source there.
    """
    import google.auth

    # A GOOGLE_APPLICATION_CREDENTIALS pointing at a missing file makes
    # default() raise rather than fall through to the metadata server.
    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if gac and not Path(gac).is_file():
        os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

    creds, _project = google.auth.default(scopes=_CLOUD_SCOPES)
    if not getattr(creds, "valid", False):
        creds.refresh(Request())
    return creds


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
        creds = _from_credentials_file(path)
        if not getattr(creds, "valid", True):
            creds.refresh(Request())
        # Refresh tokens / SA keys are long-lived; cache the access token briefly.
        expiry = getattr(creds, "expiry", None)
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        _cached = creds
        _expires = (expiry - timedelta(minutes=5)) if expiry else now + timedelta(minutes=45)
        return _cached

    # GCE / Cloud Run: the attached service account via the metadata server.
    try:
        creds = _from_application_default()
        expiry = getattr(creds, "expiry", None)
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        _cached = creds
        _expires = (expiry - timedelta(minutes=5)) if expiry else now + timedelta(minutes=45)
        return _cached
    except Exception:
        pass

    # No refresh token available: access tokens live ~1h, so keep the cache well
    # inside that window rather than assuming a run finishes before expiry.
    creds = _from_gcloud()
    _cached = creds
    _expires = now + timedelta(minutes=20)
    return _cached
