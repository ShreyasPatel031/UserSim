"""Report what a seed can actually serve, and refresh its health.json.

Runs on a seed VM. The distinction that matters: ``secrets/identities.json`` is a
global registry of credentials, so a product marked ``signed_up`` there may have
been signed up on a different machine. A fleet scheduler that trusts it will
route work to a seed holding no session for that product.

Ground truth is the cookie jar on this seed's identity disk. A product counts as
servable only if its Chrome profile carries a cookie that looks like an
authenticated session for that host.
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

# Substrings that indicate a session rather than analytics or consent state.
AUTH_HINTS = ("sess", "auth", "token", "login", "sid", "jwt", "credential")

# Analytics vendors mint cookies with "session" in the name on any page view;
# counting those is how a marketing page gets mistaken for a signed-in app.
NOISE = (
    "analytics",
    "ab.storage",
    "_ga",
    "_gid",
    "amplitude",
    "mixpanel",
    "segment",
    "intercom",
    "hubspot",
    "optimizely",
    "anti_forgery",
    "csrf",
    "xsrf",
    "logged-out",
    "logged_out",
    "logout",
    "anonymous",
    "guest",
    "session_id",
    "fpgsid",
    "__ssid",
    "_uetsid",
    "phpsessid",
    "jsessionid",
    "browser_sess",
    "monolith-login",
    "unauth",
    # TikTok / ads pixels contain "sid" but are not product sessions.
    "ttcsid",
    "_ttp",
    "_tt_enable",
    "preauth",
    # Consent / CMP (Usercentrics `_uc_current_session` contains "sess").
    "_uc_",
    "usercentrics",
)

# Products that mint opaque httpOnly session cookies (no auth-hint substring).
# Require ≥2 hits so a stray marketing cookie does not count.
OPAQUE_AUTH_COOKIES: dict[str, frozenset[str]] = {
    "canva.com": frozenset({"CDI", "CAZ", "CID", "CUI", "CUL", "CB", "CAU", "CL", "CS"}),
}


def _cookie_db(profile: Path) -> Path | None:
    for rel in ("Default/Cookies", "Default/Network/Cookies", "Cookies"):
        path = profile / rel
        if path.is_file():
            return path
    return None


def _registrable(host: str) -> str:
    """Crude eTLD+1 so app.todoist.com matches todoist.com."""
    parts = host.lstrip(".").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _is_auth_cookie_name(name: str) -> bool:
    low = str(name or "").lower()
    if any(n in low for n in NOISE):
        return False
    return any(h in low for h in AUTH_HINTS)


def session_cookies(profile: Path, host: str) -> list[str]:
    """Auth-looking cookie names scoped to the product's own domain."""
    db = _cookie_db(profile)
    if db is None:
        return []
    try:
        conn = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
        rows = conn.execute("select host_key, name from cookies").fetchall()
        conn.close()
    except sqlite3.Error:
        return []

    want = _registrable(host)
    found: set[str] = set()
    for host_key, name in rows:
        if _registrable(str(host_key)) != want:
            continue
        if _is_auth_cookie_name(str(name)):
            found.add(str(name))
    return sorted(found)


def _auth_names_from_storage(state: dict, host: str) -> list[str]:
    want = _registrable(host)
    found: set[str] = set()
    opaque_hits: set[str] = set()
    opaque_want = OPAQUE_AUTH_COOKIES.get(want, frozenset())

    for cookie in state.get("cookies") or []:
        if _registrable(str(cookie.get("domain") or "")) != want:
            continue
        name = str(cookie.get("name") or "")
        if _is_auth_cookie_name(name):
            found.add(name)
        if name in opaque_want:
            opaque_hits.add(name)

    if len(opaque_hits) >= 2:
        found.update(opaque_hits)

    # SPA auth often lives in localStorage (Canva login_stamp, Bitwarden vault keys).
    for origin in state.get("origins") or []:
        origin_host = str(origin.get("origin") or "").lower()
        if want not in origin_host:
            continue
        for item in origin.get("localStorage") or []:
            name = str(item.get("name") or "")
            low = name.lower()
            # Feature-flag SDKs embed "access_token" in key paths (Box SplitIO).
            if "split" in low or "splitio" in low:
                continue
            if low in {"login_stamp", "login_mode"} or low.startswith("login_stamp"):
                found.add(name)
                continue
            if low.startswith("user_") and (
                "vault" in low or "account" in low or "token" in low
            ):
                found.add(name)
                continue
            # Prefer exact-ish key names over substring hits in long feature keys.
            base = low.rsplit(".", 1)[-1]
            if base in {
                "access_token",
                "refresh_token",
                "refreshtoken",
                "auth_token",
                "authtoken",
            }:
                found.add(name)
    return sorted(found)


def main() -> int:
    seed_root = Path(sys.argv[1] if len(sys.argv) > 1 else "/var/lib/usersim-seed")
    if seed_root.name == "usersim-seed":
        candidates = [p for p in seed_root.iterdir() if p.is_dir()]
        if not candidates:
            print("no seed root found", file=sys.stderr)
            return 1
        seed_root = candidates[0]

    profiles_dir = seed_root / "profiles"
    states_dir = seed_root / "site_states"
    servable: dict[str, list[str]] = {}
    empty: list[str] = []
    if profiles_dir.is_dir():
        for prof in sorted(profiles_dir.iterdir()):
            if not prof.is_dir():
                continue
            names = session_cookies(prof, prof.name)
            if names:
                servable[prof.name] = names
            else:
                empty.append(prof.name)

    # Browserbase signups persist Playwright storage_state, not a Chrome profile.
    if states_dir.is_dir():
        for state_path in sorted(states_dir.glob("*.json")):
            host = state_path.stem
            if host in servable:
                continue
            try:
                state = json.loads(state_path.read_text())
            except Exception:
                continue
            names = _auth_names_from_storage(state, host)
            if names:
                servable[host] = names
            elif host not in empty and host not in servable:
                empty.append(host)

    # Don't list a host as empty if site_states already proved a session.
    empty = [h for h in empty if h not in servable]

    health_path = seed_root / "state" / "health.json"
    try:
        health = json.loads(health_path.read_text())
    except Exception:
        health = {}

    health.update(
        {
            "seed_id": seed_root.name,
            "healthy": True,
            "role": "signup",
            # Only products with a real session on THIS disk.
            "servable": sorted(servable),
            "session_cookies": servable,
            "profiles_without_session": empty,
            "auth_state": "has_accounts" if servable else "provisioned",
            "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    )
    # The global registry is credentials, not proof of a session here.
    health.pop("signed_up", None)
    health.pop("products", None)

    health_path.write_text(json.dumps(health, indent=2) + "\n")
    os.chmod(health_path, 0o600)

    print(
        json.dumps(
            {
                "seed": seed_root.name,
                "servable": sorted(servable),
                "profiles_without_session": empty,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
