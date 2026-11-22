"""Sign in with Google for token callers only.

Some products only let new accounts in through Google ("Continue with Google"). The public engine blocks Google's
sign-in pages for everyone (sessions.BLOCKED_SIGNIN_HOSTS). This module lets one Google session, the UserSim signups
account, be used by sessions whose caller sent a valid bearer token, and never by anonymous callers.

- The state is a Playwright storage_state of a signed-in Google session, in a PRIVATE object named by the env var
  MVP_GOOGLE_STATE_URI (never under seed_states/, which anonymous cells load):
      {"storage_state": {"cookies": [...], "origins": [...]}, "seed": "usersim-signup-seed-N", "saved_at": "...",
       "account": "<the gmail address>"}
- It is merged into the session's new browser context, on the seed named in "seed" (the IP Google has seen).
- Off unless limits.json google_signin_token_callers is true AND MVP_GOOGLE_STATE_URI is set AND the caller has a
  token. Anything else keeps Google blocked, exactly as before.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

CACHE_TTL_S = 300.0
_CACHE: list[Any] = [0.0, None]
_LOCK = threading.Lock()

# Hosts of Google's sign-in flow a token session may visit.
GOOGLE_SIGNIN_HOSTS = ("accounts.google.com",)


def state_uri() -> str:
    return (os.environ.get("MVP_GOOGLE_STATE_URI") or "").strip()


def allowed_for(owner: str) -> bool:
    """True when this caller may use the Google session: feature on, a state or vault configured, and a token caller
    (or any caller when google_signin_anon is on; anonymous callers stay under their daily $ cap)."""
    from mvp.sim_mcp import limits
    from mvp.sim_mcp.sessions import is_anon

    from mvp.sim_mcp import google_login

    on = bool(limits.get("google_signin_token_callers"))
    who = bool(owner) and (not is_anon(owner) or bool(limits.get("google_signin_anon")))
    return on and bool(state_uri() or google_login.configured()) and who


def load() -> dict[str, Any] | None:
    """The configured Google state entry, or None. Cached CACHE_TTL_S; a read error reads as no state."""
    now = time.time()
    with _LOCK:
        if now - _CACHE[0] < CACHE_TTL_S:
            return _CACHE[1]
    entry = None
    try:
        from mvp.gcs_store import gcs_download_json

        got = gcs_download_json(state_uri())
        st = got.get("storage_state") if isinstance(got, dict) else None
        if isinstance(st, dict) and st.get("cookies"):
            entry = got
    except Exception as exc:  # noqa: BLE001
        print(f"[google_signin] load failed: {type(exc).__name__}"[:200], flush=True)
    with _LOCK:
        _CACHE[0], _CACHE[1] = now, entry
    return entry


def merge(site_state: dict[str, Any] | None, google_state: dict[str, Any]) -> dict[str, Any]:
    """One storage_state holding the site's saved cookies (if any) plus the Google session's."""
    out: dict[str, Any] = {"cookies": [], "origins": []}
    seen: set[tuple[str, str, str]] = set()
    for st in (site_state or {}, google_state or {}):
        for c in st.get("cookies") or []:
            key = (str(c.get("name")), str(c.get("domain")), str(c.get("path")))
            if key in seen:
                continue
            seen.add(key)
            out["cookies"].append(c)
        out["origins"].extend(st.get("origins") or [])
    return out


def is_google_signin(host: str) -> bool:
    host = (host or "").lower()
    return any(host == h or host.endswith("." + h) for h in GOOGLE_SIGNIN_HOSTS)
