"""Server secrets from GCP Secret Manager with hot reload and file fallback.

Each secret is stored as ``usersim-<ENV_VAR_NAME>`` in project ``project-amer-scs-sandbox`` (override with
``USERSIM_GCP_PROJECT``). On refresh, the latest enabled version is loaded into ``os.environ`` so
existing code keeps working. If Secret Manager has no value, falls back to ``/etc/usersim/env``.

Never log or expose secret values. ``snapshot()`` only reports presence and source per variable.
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any

DEFAULT_PROJECT = "project-amer-scs-sandbox"
def _env_file() -> Path:
    return Path(os.environ.get("USERSIM_ENV_FILE", "/etc/usersim/env"))
REFRESH_S = max(60.0, float(os.environ.get("USERSIM_SECRETS_REFRESH_S", "300")))

# Env vars treated as secrets (values loaded from GSM or the env file).
SECRET_VARS: tuple[str, ...] = (
    "GMAIL_APP_PASSWORD",
    "BROWSERBASE_API_KEY",
    "MVP_CAPTCHA_API_KEY",
    "CAPSOLVER_API_KEY",
    # The Apify token and the residential proxy are not loaded here: only the fetch gateway reads them
    # (src/fetchgate/creds.py, /etc/fetchgate/credentials.env on the VM).
    "PH_TOKEN",
    "PH_CLIENT_ID",
    "PH_CLIENT_SECRET",
    "MVP_SMS_PHONE",
    "MVP_OWNER_PHONE",
    "MVP_NTFY_SMS_TOPIC",
    "MVP_NTFY_TOKEN",
    "MVP_SMS_API_KEY",
    "MVP_MCP_TOKEN",
    "MVP_TEXTVERIFIED_API_KEY",
)

_ABOUT: dict[str, str] = {
    "GMAIL_APP_PASSWORD": "Gmail IMAP app password for usersim.signups inbox (signup + verification mail).",
    "BROWSERBASE_API_KEY": "Browserbase API key for cloud browsers (MCP and website studies).",
    "MVP_CAPTCHA_API_KEY": "CapSolver (or compatible) API key for paid captcha tokens.",
    "CAPSOLVER_API_KEY": "Alias some tools use for the same CapSolver key as MVP_CAPTCHA_API_KEY.",
    "PH_TOKEN": "Product Hunt API v2 developer token (discovery, scripts/ph_crawl.py). Preferred over the client pair.",
    "PH_CLIENT_ID": "Product Hunt application client id; with PH_CLIENT_SECRET mints a public-scope token.",
    "PH_CLIENT_SECRET": "Product Hunt application client secret (pairs with PH_CLIENT_ID).",
    "MVP_SMS_PHONE": "E.164 phone number forwarded to ntfy for SMS verification codes.",
    "MVP_OWNER_PHONE": "Owner phone metadata (optional; often same as MVP_SMS_PHONE).",
    "MVP_NTFY_SMS_TOPIC": "ntfy topic name where the phone posts SMS bodies (high sensitivity).",
    "MVP_NTFY_TOKEN": "Bearer token for a private ntfy topic or server.",
    "MVP_SMS_API_KEY": "TextVerified (or other) API key when MVP_SMS_BACKEND=api.",
    "MVP_MCP_TOKEN": "Optional bearer token(s) that skip anonymous MCP caps (comma-separated).",
    "MVP_TEXTVERIFIED_API_KEY": "Legacy alias for TextVerified API key.",
}

_LOCK = threading.Lock()
_META: dict[str, dict[str, Any]] = {}
_STATE: dict[str, Any] = {"loaded_at": 0.0, "checked_at": 0.0, "error": "", "fetching": False}
_INSTALLED = False


def _project() -> str:
    return (os.environ.get("USERSIM_GCP_PROJECT") or os.environ.get("GCP_PROJECT") or DEFAULT_PROJECT).strip()


def _secret_name(var: str) -> str:
    return f"usersim-{var}"


def _read_env_file() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        text = _env_file().read_text()
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        out[key] = val
    return out


def _fetch_gsm(var: str) -> str | None:
    if os.environ.get("USERSIM_SECRETS_OFF", "").lower() in {"1", "true", "yes"}:
        return None
    name = _secret_name(var)
    project = _project()
    try:
        from google.cloud import secretmanager  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        client = secretmanager.SecretManagerServiceClient()
        path = f"projects/{project}/secrets/{name}/versions/latest"
        resp = client.access_secret_version(request={"name": path})
        return (resp.payload.data or b"").decode("utf-8").strip() or None
    except Exception:  # noqa: BLE001
        return None


def refresh_now() -> bool:
    """Reload all known secrets. True if at least one GSM read succeeded."""
    file_vals = _read_env_file()
    gsm_ok = False
    try:
        for var in SECRET_VARS:
            val: str | None = None
            source = "missing"
            gsm = _fetch_gsm(var)
            if gsm:
                val, source, gsm_ok = gsm, "secret_manager", True
            elif var in file_vals and file_vals[var].strip():
                val, source = file_vals[var].strip(), "file"
            elif (os.environ.get(var) or "").strip():
                val, source = os.environ[var].strip(), "env"
            if val:
                os.environ[var] = val
            present = bool((os.environ.get(var) or "").strip())
            with _LOCK:
                _META[var] = {"present": present, "source": source if present else "missing", "about": _ABOUT.get(var, "")}
        with _LOCK:
            _STATE.update(loaded_at=time.time(), error="")
    except Exception as exc:  # noqa: BLE001
        with _LOCK:
            _STATE["error"] = repr(exc)[:300]
    finally:
        with _LOCK:
            _STATE["checked_at"] = time.time()
            _STATE["fetching"] = False
    return gsm_ok


def _maybe_refresh() -> None:
    with _LOCK:
        if _STATE["fetching"] or time.time() - _STATE["checked_at"] < REFRESH_S:
            return
        _STATE["fetching"] = True
        _STATE["checked_at"] = time.time()
    threading.Thread(target=refresh_now, name="usersim-secrets-refresh", daemon=True).start()


def install() -> None:
    """Load secrets once at process start and start periodic refresh."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    refresh_now()
    # Prime meta for vars only in process env (local dev).
    for var in SECRET_VARS:
        with _LOCK:
            if var not in _META:
                present = bool((os.environ.get(var) or "").strip())
                _META[var] = {"present": present, "source": "env" if present else "missing", "about": _ABOUT.get(var, "")}
    threading.Thread(target=_refresh_loop, name="usersim-secrets-loop", daemon=True).start()


def _refresh_loop() -> None:
    while True:
        time.sleep(REFRESH_S)
        refresh_now()


def snapshot() -> dict[str, Any]:
    """Presence and source per secret (never values)."""
    _maybe_refresh()
    with _LOCK:
        st = dict(_STATE)
        rows = {k: dict(v) for k, v in _META.items()}
    for var in SECRET_VARS:
        rows.setdefault(var, {"present": bool((os.environ.get(var) or "").strip()), "source": "env", "about": _ABOUT.get(var, "")})
    return {
        "project": _project(),
        "env_file": str(_env_file()),
        "refresh_s": REFRESH_S,
        "loaded_at": st["loaded_at"],
        "checked_at": st["checked_at"],
        "error": st["error"],
        "secrets": rows,
    }


def reset_for_tests() -> None:
    global _INSTALLED
    _INSTALLED = False
    with _LOCK:
        _META.clear()
        _STATE.update(loaded_at=0.0, checked_at=time.time(), error="", fetching=False)
