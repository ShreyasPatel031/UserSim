"""Voice-AI product dashboards (app consoles, not marketing sites)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from config import ROOT

SESSION_DIR = ROOT / "secrets" / "voice_ai_sessions"
PROFILE_DIR = ROOT / "secrets" / "voice_ai_browser_profile"
DEFAULT_EMAIL = "shreyashfs@gmail.com"


@dataclass(frozen=True)
class VoiceAiDashboard:
    key: str
    name: str
    dashboard_url: str
    login_url: str
    google_sso: bool = True
    cookie_domains: tuple[str, ...] = ()
    session_cookie_hints: tuple[str, ...] = ("session", "auth", "token")
    logged_in_url_hints: tuple[str, ...] = ()
    logged_in_body_hints: tuple[str, ...] = (
        "logout",
        "log out",
        "sign out",
        "api key",
        "api keys",
        "billing",
        "settings",
        "agents",
        "workflows",
        "phone numbers",
    )
    login_body_hints: tuple[str, ...] = (
        "log in",
        "sign in",
        "get code",
        "continue with google",
        "sign in with google",
    )


DASHBOARDS: tuple[VoiceAiDashboard, ...] = (
    VoiceAiDashboard(
        key="bland",
        name="Bland AI",
        dashboard_url="https://app.bland.ai/dashboard",
        login_url="https://app.bland.ai/login",
        cookie_domains=(".bland.ai", "bland.ai", "app.bland.ai"),
        session_cookie_hints=("session_token", "bland-auth"),
        logged_in_url_hints=("/dashboard", "/calls", "/agents", "/call-logs"),
    ),
    VoiceAiDashboard(
        key="vapi",
        name="Vapi",
        dashboard_url="https://dashboard.vapi.ai/",
        login_url="https://dashboard.vapi.ai/login",
        cookie_domains=(".vapi.ai", "vapi.ai", "dashboard.vapi.ai"),
        session_cookie_hints=("session", "auth", "token", "jwt", "__sec__token"),
        logged_in_url_hints=("/overview", "/assistants", "/phone-numbers", "/calls", "dashboard.vapi.ai/"),
        logged_in_body_hints=("assistants", "phone numbers", "create assistant", "api keys", "logout", "log out"),
    ),
    VoiceAiDashboard(
        key="retell",
        name="Retell AI",
        dashboard_url="https://dashboard.retellai.com/",
        login_url="https://dashboard.retellai.com/login",
        cookie_domains=(".retellai.com", "retellai.com", "dashboard.retellai.com"),
        session_cookie_hints=("session", "auth", "token", "jwt"),
        logged_in_url_hints=("/agents", "/dashboard", "/calls"),
    ),
    VoiceAiDashboard(
        key="synthflow",
        name="Synthflow",
        dashboard_url="https://app.synthflow.ai/",
        login_url="https://app.synthflow.ai/login",
        logged_in_url_hints=("/assistants", "/dashboard", "/workspaces"),
    ),
    VoiceAiDashboard(
        key="elevenlabs",
        name="ElevenLabs",
        dashboard_url="https://elevenlabs.io/app",
        login_url="https://elevenlabs.io/app/sign-in",
        logged_in_url_hints=("/app/speech-synthesis", "/app/home", "/app/conversational-ai"),
        logged_in_body_hints=("speech synthesis", "voices", "conversational ai", "logout"),
    ),
    VoiceAiDashboard(
        key="telnyx",
        name="Telnyx",
        dashboard_url="https://portal.telnyx.com/#/home",
        login_url="https://portal.telnyx.com/#/login",
        google_sso=True,
        logged_in_url_hints=("/home", "/messaging", "/voice"),
    ),
)

DASHBOARD_BY_KEY = {d.key: d for d in DASHBOARDS}


def session_path(key: str) -> Path:
    return SESSION_DIR / f"{key}.json"


def sanitize_storage_state_dict(data: dict) -> dict:
    """Playwright-compatible storage_state (strip CHIPS partitionKey objects, etc.)."""
    cookies = []
    for c in data.get("cookies") or []:
        row = dict(c)
        pk = row.get("partitionKey")
        if pk is not None and not isinstance(pk, str):
            row.pop("partitionKey", None)
        row["secure"] = bool(row.get("secure"))
        row["httpOnly"] = bool(row.get("httpOnly"))
        row.setdefault("sameSite", "Lax")
        if row.get("expires") is None:
            row["expires"] = -1
        cookies.append(row)
    origins = []
    for o in data.get("origins") or []:
        row = dict(o)
        row["localStorage"] = row.get("localStorage") or []
        origins.append(row)
    return {"cookies": cookies, "origins": origins}


def load_storage_state(key: str) -> dict | None:
    sp = session_path(key)
    if not sp.is_file():
        return None
    return sanitize_storage_state_dict(json.loads(sp.read_text()))


def write_sanitized_session(key: str) -> None:
    sp = session_path(key)
    if not sp.is_file():
        return
    data = sanitize_storage_state_dict(json.loads(sp.read_text()))
    sp.write_text(json.dumps(data, indent=2))


def _jwt_claims(token: str) -> dict:
    import base64

    segment = token.split(".")[1]
    pad = "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(segment + pad))


def refresh_vapi_workos_session(
    *,
    client_id: str = "client_01JS5DFXFQRR9DVGVCG18WKT2T",
    organization_id: str | None = None,
) -> dict:
    """Exchange workos_rt cookie for fresh Vapi localStorage JWTs (~1h TTL).

    Call immediately before fleet pack / at Vapi shard start so agents do not
    begin on expired WorkOS access tokens.
    """
    import shutil
    import time
    import urllib.request
    from datetime import datetime, timezone

    sp = session_path("vapi")
    if not sp.is_file():
        raise FileNotFoundError(sp)
    raw = json.loads(sp.read_text())
    rt_cookie = next((c for c in raw.get("cookies") or [] if c.get("name") == "workos_rt"), None)
    if not rt_cookie or not rt_cookie.get("value"):
        raise RuntimeError("vapi session missing workos_rt cookie — re-export from browser")

    org_id = organization_id
    if not org_id:
        for o in raw.get("origins") or []:
            for e in o.get("localStorage") or []:
                if e.get("name") == "ORG_TOKEN" and e.get("value"):
                    try:
                        org_id = _jwt_claims(e["value"]).get("org_id") or org_id
                    except Exception:
                        pass
    org_id = org_id or "org_01M109ECMA5WJQ3GAZKERY86EH"

    def _auth(refresh_token: str, organization_id: str | None) -> dict:
        body: dict = {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        if organization_id:
            body["organization_id"] = organization_id
        req = urllib.request.Request(
            "https://api.workos.com/user_management/authenticate",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode())

    first = _auth(rt_cookie["value"], None)
    rt2 = first.get("refresh_token") or rt_cookie["value"]
    org = _auth(rt2, org_id)
    access = org["access_token"]
    final_rt = org.get("refresh_token") or rt2
    claims = _jwt_claims(access)
    exp = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)

    bak = sp.with_suffix(f".json.bak_refresh_{int(time.time())}")
    shutil.copy(sp, bak)
    for o in raw.get("origins") or []:
        if o.get("origin") != "https://dashboard.vapi.ai":
            continue
        ls = o.setdefault("localStorage", [])
        by_name = {e["name"]: e for e in ls}
        for name in ("USER_TOKEN", "ORG_TOKEN", "WORKOS_ACCESS_TOKEN"):
            if name in by_name:
                by_name[name]["value"] = access
            else:
                ls.append({"name": name, "value": access})
    for c in raw.get("cookies") or []:
        if c.get("name") == "workos_rt":
            c["value"] = final_rt
            c["expires"] = time.time() + 30 * 86400
            break

    cleaned = sanitize_storage_state_dict(raw)
    for c in cleaned.get("cookies") or []:
        if c.get("name") == "workos_rt":
            c["value"] = final_rt
            c["expires"] = time.time() + 30 * 86400
    for o in cleaned.get("origins") or []:
        if o.get("origin") != "https://dashboard.vapi.ai":
            continue
        ls = o.setdefault("localStorage", [])
        by_name = {e["name"]: e for e in ls}
        for name in ("USER_TOKEN", "ORG_TOKEN", "WORKOS_ACCESS_TOKEN"):
            if name in by_name:
                by_name[name]["value"] = access
            else:
                ls.append({"name": name, "value": access})
    sp.write_text(json.dumps(cleaned, indent=2))
    return {
        "exp": exp.isoformat(),
        "org_id": claims.get("org_id"),
        "email": claims.get("email"),
        "backup": str(bak),
        "session": str(sp),
    }


def has_saved_session(key: str) -> bool:
    return session_path(key).is_file()


# Product-console smoke tasks (not Mind2Web). eval_index 9000+.
PRODUCT_BLAND_TASKS: tuple[dict, ...] = (
    {
        "task_id": "bland-product-smoke-1",
        "eval_index": 9001,
        "website": "bland",
        "domain": "voice_ai_product",
        "task": (
            "You are on the Bland AI product console (logged in). "
            "Open Call Logs from the sidebar. "
            "Report the current URL — success if URL contains call-logs and not login."
        ),
        "start_url": "https://app.bland.ai/dashboard",
        "human_n_steps": 8,
        "human_actions": [],
    },
)

PRODUCT_VAPI_TASKS: tuple[dict, ...] = (
    {
        "task_id": "vapi-product-smoke-1",
        "eval_index": 9002,
        "website": "vapi",
        "domain": "voice_ai_product",
        "task": (
            "You are on the Vapi product dashboard (logged in). "
            "Confirm you are NOT on the login page. "
            "Open Assistants (or Phone Numbers) from the sidebar. "
            "Report the current URL and whether you see assistant or phone number UI."
        ),
        "start_url": "https://dashboard.vapi.ai/",
        "human_n_steps": 8,
        "human_actions": [],
    },
)

PRODUCT_RETELL_TASKS: tuple[dict, ...] = (
    {
        "task_id": "retell-product-smoke-1",
        "eval_index": 9003,
        "website": "retell",
        "domain": "voice_ai_product",
        "task": (
            "You are on the Retell AI product dashboard (logged in). "
            "Confirm you are NOT on the login page. "
            "Open Agents from the sidebar. "
            "Report the current URL and whether you see an agents list or create-agent UI."
        ),
        "start_url": "https://dashboard.retellai.com/",
        "human_n_steps": 8,
        "human_actions": [],
    },
)

PRODUCT_STAGE_TASKS: dict[str, tuple[dict, ...]] = {
    "product_bland": PRODUCT_BLAND_TASKS,
    "product_vapi": PRODUCT_VAPI_TASKS,
    "product_retell": PRODUCT_RETELL_TASKS,
    "product_retell_vapi": PRODUCT_RETELL_TASKS + PRODUCT_VAPI_TASKS,
    "product_all": PRODUCT_BLAND_TASKS + PRODUCT_RETELL_TASKS + PRODUCT_VAPI_TASKS,
}


def dashboard_for_url(url: str) -> VoiceAiDashboard | None:
    low = (url or "").lower()
    host_to_key = {
        "app.bland.ai": "bland",
        "dashboard.vapi.ai": "vapi",
        "dashboard.retellai.com": "retell",
        "app.synthflow.ai": "synthflow",
        "elevenlabs.io": "elevenlabs",
        "portal.telnyx.com": "telnyx",
    }
    for host, key in host_to_key.items():
        if host in low:
            return DASHBOARD_BY_KEY[key]
    return None


def browser_profile_overrides(start_url: str) -> dict:
    """Playwright/BrowserProfile kwargs for authenticated voice-AI app URLs."""
    import os

    dash = dashboard_for_url(start_url)
    if not dash:
        return {}
    if os.environ.get("VOICE_AI_AUTH", "1").lower() in {"0", "false", "no"}:
        return {}
    overrides: dict = {}
    state = load_storage_state(dash.key)
    if state:
        # Prefer sanitized dict (origins always have localStorage) over raw path.
        overrides["storage_state"] = state
    elif PROFILE_DIR.is_dir():
        overrides["user_data_dir"] = str(PROFILE_DIR)
        overrides["channel"] = "chrome"
        overrides["ignore_default_args"] = ["--enable-automation"]
        overrides["args"] = ["--disable-blink-features=AutomationControlled"]
    return overrides
