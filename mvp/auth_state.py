"""Auth / storage_state helpers for MVP browser agents."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse

from capability.voice_ai_dashboards import sanitize_storage_state_dict  # noqa: F401 — alias kept stable

# Prefer the canonical helper name used across the repo.
sanitize_storage_state = sanitize_storage_state_dict

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "secrets"
YOUTUBE_STATE = SECRETS / "youtube_storage_state.json"
VAPI_STATE = SECRETS / "voice_ai_sessions" / "vapi.json"
RETELL_STATE = SECRETS / "voice_ai_sessions" / "retell.json"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    if isinstance(data, list):
        data = {"cookies": data, "origins": []}
    if not isinstance(data, dict):
        return None
    return sanitize_storage_state_dict(data)


def _normalize_cookie(cookie: dict[str, Any]) -> dict[str, Any] | None:
    """Coerce a cookie into a shape both Playwright and CDP accept.

    partitionKey is the trap: Playwright's storage_state wants a string while
    CDP Network.setCookies wants a map, and either side rejects the *entire*
    cookie list on mismatch — which silently drops the agent to signed-out.
    Google's auth cookies are unpartitioned, so dropping the field is safe.
    """
    if not cookie.get("name"):
        return None
    out = dict(cookie)
    out.pop("partitionKey", None)
    if out.get("sameSite") not in {"Strict", "Lax", "None"}:
        out["sameSite"] = "Lax"
    if out["sameSite"] == "None" and not out.get("secure"):
        out["sameSite"] = "Lax"
    return out


def _merge_states(*states: dict[str, Any] | None) -> dict[str, Any] | None:
    cookies: list[dict[str, Any]] = []
    origins: list[dict[str, Any]] = []
    seen_cookie: set[tuple[str, str, str]] = set()
    seen_origin: set[str] = set()
    for state in states:
        if not state:
            continue
        for c in state.get("cookies") or []:
            key = (c.get("domain") or "", c.get("path") or "/", c.get("name") or "")
            if key in seen_cookie:
                continue
            normalized = _normalize_cookie(c)
            if not normalized:
                continue
            seen_cookie.add(key)
            cookies.append(normalized)
        for o in state.get("origins") or []:
            origin = o.get("origin") or ""
            if not origin or origin in seen_origin:
                continue
            seen_origin.add(origin)
            origins.append(o)
    if not cookies and not origins:
        return None
    return {"cookies": cookies, "origins": origins}


def _cookie_has_login(state: dict[str, Any] | None) -> bool:
    if not state:
        return False
    return any(c.get("name") == "LOGIN_INFO" for c in (state.get("cookies") or []))


YOUTUBE_PROFILE = SECRETS / "youtube_browser_profile"
YOUTUBE_AUTH_OK = SECRETS / "youtube_auth_ok"
YOUTUBE_STATE_SIGNED = SECRETS / "youtube_storage_state.json.signed"


def mark_youtube_auth_ok(ok: bool = True) -> None:
    if ok:
        YOUTUBE_AUTH_OK.write_text("ok\n")
    elif YOUTUBE_AUTH_OK.exists():
        YOUTUBE_AUTH_OK.unlink()


def youtube_auth_capture_ready() -> bool:
    """True only after interactive refresh_youtube_auth succeeded.

    browser_cookie3 / voice-AI cookie dumps often include LOGIN_INFO but do NOT
    authenticate YouTube/Gmail in Playwright — do not treat those as signed-in.
    """
    if not YOUTUBE_AUTH_OK.is_file():
        return False
    return _cookie_has_login(_load_json(YOUTUBE_STATE_SIGNED)) or _cookie_has_login(
        _load_json(YOUTUBE_STATE)
    )


def storage_state_for_url(url: str) -> dict[str, Any] | None:
    """Best-effort signed-in storage for the target host."""
    host = (urlparse(url).hostname or "").lower()
    states: list[dict[str, Any] | None] = []

    # Prefer a dedicated YouTube/Google export when present.
    if "youtube.com" in host or "google." in host:
        # Only the interactive capture (mvp.refresh_youtube_auth) produces a
        # storage_state that actually signs Playwright into YouTube.
        states.append(_load_json(YOUTUBE_STATE_SIGNED))
        states.append(_load_json(YOUTUBE_STATE))
        if youtube_auth_capture_ready():
            # A verified session is self-sufficient; stale Google cookies from other
            # dumps only risk conflicting with it.
            return _merge_states(*states)
        # Voice-AI dumps: useful for some Google surfaces, not YouTube home auth.
        for path in (VAPI_STATE, RETELL_STATE):
            raw = _load_json(path)
            if not raw:
                continue
            filtered = {
                "cookies": [
                    c
                    for c in (raw.get("cookies") or [])
                    if any(
                        x in (c.get("domain") or "").lower()
                        for x in ("google", "youtube", "gstatic", "ggpht")
                    )
                ],
                "origins": [
                    o
                    for o in (raw.get("origins") or [])
                    if any(x in (o.get("origin") or "").lower() for x in ("google", "youtube"))
                ],
            }
            states.append(sanitize_storage_state_dict(filtered))
    else:
        # Generic: allow an explicit per-host dump at secrets/{host}_storage_state.json
        safe = re.sub(r"[^a-z0-9.-]+", "_", host)
        states.append(_load_json(SECRETS / f"{safe}_storage_state.json"))
        states.append(_load_json(YOUTUBE_STATE))

    return _merge_states(*states)


def youtube_is_signed_in(state: dict[str, Any] | None = None) -> bool:
    if not youtube_auth_capture_ready():
        return False
    state = state or _load_json(YOUTUBE_STATE)
    return _cookie_has_login(state)


def youtube_needs_content_bootstrap(url: str, storage_state: dict[str, Any] | None = None) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if "youtube.com" not in host and "youtu.be" not in host:
        return False
    path = (urlparse(url).path or "/").rstrip("/") or "/"
    if path not in {"/", "/feed", "/feed/trending", "/feed/explore", "/feed/subscriptions"}:
        return False
    # Signed-in sessions get a real home feed — do not hijack to search.
    if youtube_is_signed_in(storage_state):
        return False
    # Home / feed pages are empty for signed-out automation Chromium.
    return True


def youtube_bootstrap_url(task_prompt: str = "", persona_name: str = "") -> str:
    """Search results always render video tiles even when the home feed is empty."""
    seed = (task_prompt or persona_name or "interesting videos").strip()
    # Keep query short and concrete.
    seed = re.sub(r"\s+", " ", seed)[:80]
    return f"https://www.youtube.com/results?search_query={quote_plus(seed)}"


def ensure_youtube_state_file() -> Path:
    """Materialize a youtube storage_state from the best available Google cookies."""
    state = storage_state_for_url("https://www.youtube.com/")
    if state:
        YOUTUBE_STATE.write_text(json.dumps(state, indent=2))
    return YOUTUBE_STATE
