"""The only code that reads fetch credentials: the residential proxy (DataImpulse) and the Apify token.

Where they come from, first found wins:
  1. overrides passed with the call: keys a user typed into the /discovery form for one run (their own account)
  2. the gateway's credentials file, FETCHGATE_CREDENTIALS (default /etc/fetchgate/credentials.env, KEY=VALUE lines;
     on the VM owned by the `fetchgate` user, mode 600, so agent scripts cannot read it)
  3. this process's environment
  4. the keys saved through the /discovery page (MVP_DISCOVERY_KEYS_FILE, default /var/lib/usersim/discovery_keys.json)
  5. Apify only: ~/.config/apify/token

Nothing here returns a value to an HTTP client or prints one; redact() strips them from error messages.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

APIFY = "APIFY_TOKEN"
RESIDENTIAL = "PROXY_URL"
NAMES = (APIFY, RESIDENTIAL)
# The credentials file may also name the residential proxy this way (clearer next to other gateway settings).
_ALIASES = {RESIDENTIAL: ("PROXY_URL", "RESIDENTIAL_PROXY_URL")}


def _file_values(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:  # missing, or not ours to read (that is the point on the VM)
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.removeprefix("export ").split("=", 1)
        out[k.strip()] = v.strip().strip("'\"")
    return out


def _saved_keys() -> dict[str, str]:
    path = os.environ.get("MVP_DISCOVERY_KEYS_FILE") or "/var/lib/usersim/discovery_keys.json"
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return {k: str(v).strip() for k, v in data.items() if k in NAMES and str(v or "").strip()}


def get(name: str, overrides: dict[str, str] | None = None) -> str:
    """One credential ('' when none is available to this process)."""
    if (overrides or {}).get(name, "").strip():
        return overrides[name].strip()
    keys = _ALIASES.get(name, (name,))
    filed = _file_values(os.environ.get("FETCHGATE_CREDENTIALS") or "/etc/fetchgate/credentials.env")
    for k in keys:
        if filed.get(k):
            return filed[k]
    for k in keys:
        if (os.environ.get(k) or "").strip():
            return os.environ[k].strip()
    if _saved_keys().get(name):
        return _saved_keys()[name]
    if name == APIFY:
        f = Path.home() / ".config" / "apify" / "token"
        try:
            return f.read_text().strip()
        except OSError:
            return ""
    return ""


def residential(overrides: dict[str, str] | None = None) -> str:
    return get(RESIDENTIAL, overrides)


def apify_token(overrides: dict[str, str] | None = None) -> str:
    return get(APIFY, overrides)


def redact(msg: str, *secrets: str) -> str:
    """An error message without proxy logins or tokens."""
    for s in secrets:
        if s:
            msg = msg.replace(s, "<redacted>")
    msg = re.sub(r"//[^@\s/]+@", "//<redacted>@", msg)
    msg = re.sub(r"apify_api_[A-Za-z0-9]+", "<redacted>", msg)
    return re.sub(r"token=[^&\s')\"]+", "token=<redacted>", msg)
