"""Autonomous product signup for agent browser sessions.

Drives a real Chrome window through account creation on an arbitrary product
using a browser-use Agent plus deterministic tools for identity, email codes,
SMS codes, TOTP, and CAPTCHA. The artifact is a persistent Chrome profile at
``secrets/product_profiles/{host}/`` that subsequent persona agents clone.

Usage:
  PYTHONPATH=src:. .venv/bin/python -m mvp.auto_signup --url https://linear.app
  PYTHONPATH=src:. .venv/bin/python -m mvp.auto_signup --url https://www.notion.so --headed
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from mvp.captcha import solve_captcha_on_page
from mvp.credentials import totp_code
from mvp.email_codes import wait_for_signup_code, wait_for_signup_link
from mvp.identity import (
    Identity,
    host_for_url,
    provision_identity,
    safe_host,
    update_identity,
)
from mvp.signup_lessons import (
    loop_detector_signal,
    loop_tips_followup,
    lookup_tips,
    record_observation,
    should_inject_loop_tips,
)
from mvp.sms_provider import Number, lease_number, release, wait_for_sms

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "secrets"
SITE_STATES = SECRETS / "site_states"
STEP_DIR_ROOT = SECRETS / "signup_steps"
PRODUCT_PROFILES = SECRETS / "product_profiles"
CDP_PORT_DEFAULT = int(os.environ.get("MVP_SIGNUP_CDP_PORT", "9333"))

BLOCK_REASONS = (
    "card_required",
    "sso_only",
    "invite_only",
    "waitlist",
    "captcha_unsolved",
    "rate_limited",
    "unknown",
)

# Soft product gates — do not burn proxy/Verified quota retrying these.
_HARD_BLOCK_REASONS = frozenset(
    {"card_required", "sso_only", "invite_only", "waitlist"}
)

_ANTIBOT_KINDS = frozenset({"captcha", "rate_limit", "ip_block", "bot_block"})


def _bb_flag_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


class AntibotUnwedge(BaseException):
    """Injected to break a wedged agent.run after escalate (not an Exception)."""


def _cheap_bb_flags() -> dict[str, bool]:
    """Default Browserbase create flags — no paid antibot until needed."""
    return {
        "proxies": _bb_flag_bool("MVP_SIGNUP_BB_PROXIES", False),
        "solve_captchas": _bb_flag_bool("MVP_SIGNUP_BB_CAPTCHA", False),
        "advanced_stealth": _bb_flag_bool("MVP_SIGNUP_BB_VERIFIED", False),
    }


def _next_antibot_flags(
    current: dict[str, Any] | None, kind: str
) -> dict[str, bool] | None:
    """Conditional escalate for the observed blocker. Returns None at ceiling.

    Ladder (quota-aware — only climb when this kind requires it):
      captcha     → solve_captchas → +proxies → +advanced_stealth (Verified)
      rate_limit  → proxies (+captcha) → +advanced_stealth
      ip_block    → same as rate_limit
      bot_block   → proxies+captcha+advanced_stealth in one step
    """
    kind = (kind or "").strip().lower().replace("-", "_")
    aliases = {
        "captcha_unsolved": "captcha",
        "rate_limited": "rate_limit",
        "ip_blocked": "ip_block",
        "fingerprint": "bot_block",
        "verified": "bot_block",
    }
    kind = aliases.get(kind, kind)
    if kind not in _ANTIBOT_KINDS:
        return None

    cur = {
        "proxies": bool((current or {}).get("proxies")),
        "solve_captchas": bool((current or {}).get("solve_captchas")),
        "advanced_stealth": bool((current or {}).get("advanced_stealth")),
    }
    nxt = dict(cur)

    if kind == "captcha":
        if not cur["solve_captchas"]:
            nxt["solve_captchas"] = True
        elif not cur["proxies"]:
            nxt["proxies"] = True
        elif not cur["advanced_stealth"]:
            nxt["advanced_stealth"] = True
        else:
            return None
    elif kind in {"rate_limit", "ip_block"}:
        if not cur["proxies"]:
            nxt["proxies"] = True
            nxt["solve_captchas"] = True
        elif not cur["advanced_stealth"]:
            nxt["advanced_stealth"] = True
        else:
            return None
    else:  # bot_block
        if cur["proxies"] and cur["solve_captchas"] and cur["advanced_stealth"]:
            return None
        nxt = {
            "proxies": True,
            "solve_captchas": True,
            "advanced_stealth": True,
        }

    if nxt == cur:
        return None
    return nxt


def _plan_fallback_ladder(desired: dict[str, bool]) -> list[dict[str, bool]]:
    """Try desired flags first; if the plan 402/403s, strip expensive bits."""
    desired = {
        "proxies": bool(desired.get("proxies")),
        "solve_captchas": bool(desired.get("solve_captchas")),
        "advanced_stealth": bool(desired.get("advanced_stealth")),
    }
    ladder = [desired]
    stripped = dict(desired)
    if stripped.get("advanced_stealth"):
        stripped = {**stripped, "advanced_stealth": False}
        ladder.append(stripped)
    if stripped.get("proxies"):
        stripped = {**stripped, "proxies": False}
        ladder.append(stripped)
    if stripped.get("solve_captchas"):
        stripped = {**stripped, "solve_captchas": False}
        ladder.append(stripped)
    out: list[dict[str, bool]] = []
    seen: set[tuple[bool, bool, bool]] = set()
    for item in ladder:
        key = (item["proxies"], item["solve_captchas"], item["advanced_stealth"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _find_chrome() -> str:
    override = os.environ.get("MVP_CHROME_PATH")
    if override and Path(override).exists():
        return override
    for path in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/local/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ):
        if Path(path).exists():
            return path
    # Playwright-bundled Chromium (VM / Linux fallback). Binary is often a symlink.
    cache = Path.home() / ".cache" / "ms-playwright"
    if cache.is_dir():
        for cand in sorted(cache.glob("chromium-*/chrome-linux*/chrome"), reverse=True):
            if cand.exists():
                return str(cand.resolve())
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            exe = p.chromium.executable_path
            if exe and Path(exe).exists():
                return exe
    except Exception:
        pass
    raise RuntimeError("Chrome/Chromium not found; set MVP_CHROME_PATH")


def _kill_port(port: int) -> None:
    try:
        out = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True).strip()
    except Exception:
        return
    for pid in out.split():
        try:
            os.kill(int(pid), signal.SIGTERM)
        except Exception:
            pass
    time.sleep(0.8)


def _create_signup_browserbase_session(desired: dict[str, bool] | None = None):
    """Create a Browserbase session with the requested antibot flags only.

    Default is cheap (no proxies / captcha / Verified). Escalation passes a
    richer ``desired`` after the agent hits captcha or IP/rate blocks. If the
    plan rejects a flag (402/403), walk *down* from that request — never up.
    """
    from capability.browserbase_client import create_session

    desired = dict(desired or _cheap_bb_flags())
    last_exc: BaseException | None = None
    for kwargs in _plan_fallback_ladder(desired):
        try:
            # keep_alive so we can snapshot cookies after browser-use tears
            # down its BrowserSession (otherwise Linear/etc. win then lose state).
            # Always pass explicit bools so env MVP_CAPTCHA_SOLVER cannot
            # silently enable advanced stealth on a cheap session.
            session = create_session(
                keep_alive=True,
                proxies=bool(kwargs["proxies"]),
                solve_captchas=bool(kwargs["solve_captchas"]),
                advanced_stealth=bool(kwargs["advanced_stealth"]),
            )
            print(
                f"Browserbase create ok with {kwargs}",
                flush=True,
                file=__import__("sys").stderr,
            )
            return session, kwargs
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(
                f"Browserbase create refused {kwargs}: {type(exc).__name__}: {exc}"[:240],
                flush=True,
                file=__import__("sys").stderr,
            )
    assert last_exc is not None
    raise last_exc

def _signup_uses_browserbase() -> bool:
    """Signup via Browserbase when available and not forced local.

    Local Chrome on a GCP seed shares a datacenter ASN and fails captchas that a
    residential Browserbase session often clears. Default ON when
    ``BROWSERBASE_API_KEY`` is present. Explicit ``MVP_SIGNUP_BROWSERBASE=0`` /
    ``USE_BROWSERBASE=0`` or ``MVP_FORCE_LOCAL_BROWSER=1`` disables it.
    """
    if os.environ.get("MVP_FORCE_LOCAL_BROWSER", "").lower() in {"1", "true", "yes"}:
        return False
    raw = (
        os.environ.get("MVP_SIGNUP_BROWSERBASE")
        or os.environ.get("USE_BROWSERBASE")
        or ""
    ).strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    # Auto-enable on seeds that already carry Browserbase credentials.
    return bool(
        (os.environ.get("BROWSERBASE_API_KEY") or "").strip()
        and (os.environ.get("BROWSERBASE_PROJECT_ID") or "").strip()
    )


def _launch_chrome(
    start_url: str,
    profile: Path,
    *,
    headed: bool = True,
    cdp_port: int = CDP_PORT_DEFAULT,
) -> subprocess.Popen:
    profile.mkdir(parents=True, exist_ok=True)
    _kill_port(cdp_port)
    for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        target = profile / lock
        if target.exists() or target.is_symlink():
            try:
                target.unlink()
            except OSError:
                pass
    cmd = [
        _find_chrome(),
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={profile.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--window-size=1440,900",
        start_url,
    ]
    # GCP/small VMs: Chromium dies without these (sandbox + tiny /dev/shm).
    if sys.platform.startswith("linux"):
        cmd[1:1] = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ]
    if not headed or not os.environ.get("DISPLAY"):
        # Seed VMs have no X server; headed Chrome exits with "Missing X server".
        if "--headless=new" not in cmd:
            cmd.insert(1, "--headless=new")
    elif os.environ.get("MVP_CHROME_OFFSCREEN", "").lower() in {"1", "true", "yes"}:
        # Headless Chrome is fingerprinted and draws a CAPTCHA on figma, loom and
        # dropbox where headed does not. Keep the headed browser but park the
        # window off-screen so a batch run does not take over the desktop.
        cmd.insert(-1, "--window-position=-3000,-3000")
    log = open("/tmp/auto_signup_chrome.log", "ab")
    return subprocess.Popen(cmd, stdout=log, stderr=log, start_new_session=True)


# Signup deep-links, keyed by bare host. Starting on the marketing homepage
# burns several steps hunting for "Sign up" and, on slow sites, the agent
# re-navigates in a loop (dropbox spent 6 of 20 steps that way).
SIGNUP_START: dict[str, str] = {
    "airtable.com": "https://airtable.com/signup",
    "asana.com": "https://app.asana.com/-/signup",
    "bitwarden.com": "https://vault.bitwarden.com/#/register",
    "box.com": "https://account.box.com/signup/personal",
    "buffer.com": "https://login.buffer.com/signup",
    "calendly.com": "https://calendly.com/signup",
    "canva.com": "https://www.canva.com/signup",
    "clickup.com": "https://app.clickup.com/signup",
    "coda.io": "https://coda.io/signup",
    "digitalocean.com": "https://cloud.digitalocean.com/registrations/new",
    "discord.com": "https://discord.com/register",
    "dropbox.com": "https://www.dropbox.com/register",
    "evernote.com": "https://www.evernote.com/Signup.action",
    "figma.com": "https://www.figma.com/signup",
    "github.com": "https://github.com/signup",
    "gitlab.com": "https://gitlab.com/users/sign_up",
    "hubspot.com": "https://app.hubspot.com/signup-hubspot/crm",
    "linear.app": "https://linear.app/signup",
    "loom.com": "https://www.loom.com/signup",
    "mailchimp.com": "https://login.mailchimp.com/signup/new-business",
    "medium.com": "https://medium.com/m/signin",
    "miro.com": "https://miro.com/signup/",
    "monday.com": "https://auth.monday.com/users/sign_up",
    "netlify.com": "https://app.netlify.com/signup",
    "notion.so": "https://www.notion.so/signup",
    "pinterest.com": "https://www.pinterest.com/signup/",
    "posthog.com": "https://us.posthog.com/signup",
    "reddit.com": "https://www.reddit.com/register/",
    "replit.com": "https://replit.com/signup",
    "smartsheet.com": "https://app.smartsheet.com/b/home?form=signup",
    "substack.com": "https://substack.com/sign-up",
    "supabase.com": "https://supabase.com/dashboard/sign-up",
    "todoist.com": "https://todoist.com/auth/signup",
    "trello.com": "https://trello.com/signup",
    "typeform.com": "https://admin.typeform.com/signup",
    "vercel.com": "https://vercel.com/signup",
    "webflow.com": "https://webflow.com/signup",
    "wix.com": "https://users.wix.com/signin?modeLoginOrSignUp=signup",
    "wordpress.com": "https://wordpress.com/start",
    "zoom.us": "https://www.zoom.us/signup",
}


def signup_start_url(host: str) -> str:
    """Deep signup link for ``host``, else its https homepage."""
    key = (host or "").lower().removeprefix("www.")
    return SIGNUP_START.get(key, f"https://www.{key}" if key else "")


# Authenticated landing routes, tried when the agent finishes on a marketing
# page. Signing up for canva ends on canva.com, which looks logged out.
VERIFY_URLS: dict[str, list[str]] = {
    "airtable.com": ["https://airtable.com/workspaces"],
    "asana.com": ["https://app.asana.com/"],
    "bitwarden.com": ["https://vault.bitwarden.com/#/vault"],
    "box.com": ["https://app.box.com/"],
    "buffer.com": ["https://publish.buffer.com/"],
    "calendly.com": ["https://calendly.com/event_types/user/me"],
    "canva.com": ["https://www.canva.com/projects"],
    "clickup.com": ["https://app.clickup.com/"],
    "coda.io": ["https://coda.io/docs"],
    "digitalocean.com": ["https://cloud.digitalocean.com/"],
    "discord.com": ["https://discord.com/channels/@me"],
    "dropbox.com": ["https://www.dropbox.com/home"],
    "evernote.com": ["https://www.evernote.com/client/web"],
    "figma.com": ["https://www.figma.com/files"],
    "github.com": ["https://github.com/"],
    "gitlab.com": ["https://gitlab.com/dashboard"],
    "hubspot.com": ["https://app.hubspot.com/"],
    "linear.app": ["https://linear.app/"],
    "loom.com": ["https://www.loom.com/looms/videos"],
    "mailchimp.com": ["https://admin.mailchimp.com/"],
    "medium.com": ["https://medium.com/me/stories/public"],
    "miro.com": ["https://miro.com/app/dashboard/"],
    "monday.com": ["https://monday.com/"],
    "netlify.com": ["https://app.netlify.com/"],
    "notion.so": ["https://www.notion.so/"],
    "pinterest.com": ["https://www.pinterest.com/"],
    "posthog.com": ["https://us.posthog.com/"],
    "reddit.com": ["https://www.reddit.com/"],
    "replit.com": ["https://replit.com/~"],
    "smartsheet.com": ["https://app.smartsheet.com/"],
    "substack.com": ["https://substack.com/"],
    "supabase.com": ["https://supabase.com/dashboard/projects"],
    "todoist.com": ["https://app.todoist.com/app/inbox"],
    "trello.com": ["https://trello.com/"],
    "typeform.com": ["https://admin.typeform.com/"],
    "vercel.com": ["https://vercel.com/dashboard"],
    "webflow.com": ["https://webflow.com/dashboard"],
    "wix.com": ["https://manage.wix.com/dashboard"],
    "wordpress.com": ["https://wordpress.com/home"],
    "zoom.us": ["https://zoom.us/profile"],
}


def _storage_state_looks_authed(state: dict[str, Any], host: str) -> bool:
    """True if Playwright storage_state carries an auth-looking cookie for host.

    Used when the live DOM heuristic lags SPA onboarding. Same idea as
    ``scripts/vm/seed_status.py``, kept local so signup doesn't import the VM tool.
    """
    want = (host or "").lower().removeprefix("www.")
    if "." in want:
        want = ".".join(want.split(".")[-2:])
    auth_hints = ("sess", "auth", "token", "login", "sid", "jwt", "credential")
    noise = (
        "analytics",
        "ab.storage",
        "_ga",
        "_gid",
        "csrf",
        "xsrf",
        "anti_forgery",
        "intercom",
        "logged-out",
        "logged_out",
        "logout",
        "anonymous",
        "guest",
        "marketing",
        "session_id",
        "fpgsid",
        "__ssid",
        "phpsessid",
        "jsessionid",
        "browser_sess",
        "monolith-login",
        "unauth",
    )
    for cookie in state.get("cookies") or []:
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        parts = domain.split(".")
        etld = ".".join(parts[-2:]) if len(parts) >= 2 else domain
        if etld != want and want not in domain:
            continue
        name = str(cookie.get("name") or "").lower()
        if any(n in name for n in noise):
            continue
        if any(h in name for h in auth_hints):
            return True
    # Bitwarden (and similar) keep account records in localStorage, not cookies.
    for origin in state.get("origins") or []:
        origin_host = str(origin.get("origin") or "").lower()
        if want not in origin_host and not origin_host.endswith(want):
            continue
        for item in origin.get("localStorage") or []:
            name = str(item.get("name") or "")
            low = name.lower()
            if low.startswith("user_") and ("vault" in low or "account" in low or "token" in low):
                return True
            if "access_token" in low or "refreshtoken" in low or "authtoken" in low:
                return True
    return False


async def verify_signed_in(page: Any, host: str) -> bool:
    """Probe the current page, then the product's authenticated routes."""
    if await _looks_signed_in(page):
        return True
    key = (host or "").lower().removeprefix("www.")
    for url in VERIFY_URLS.get(key, []):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(4)
        except Exception:
            continue
        if await _looks_signed_in(page):
            return True
    return False


def site_state_path(host: str) -> Path:
    return SITE_STATES / f"{safe_host(host)}.json"


_AUTH_COOKIE_RE = re.compile(
    r"(session|token|auth|sid|login|_user|account)", re.I
)
# Cookies every visitor gets; they say nothing about being logged in.
_AUTH_COOKIE_SKIP = re.compile(
    r"(csrf|xsrf|consent|cookie|gdpr|locale|lang|theme|device|visitor|anon|"
    r"^_ga|^_gid|^_fbp|^ajs_anonymous|amplitude|segment|intercom|hubspot|optimizely)",
    re.I,
)


async def _looks_signed_in(page: Any) -> bool:
    """Whether the page is an authenticated app view.

    The old version only matched logout links and avatars, so SPAs that keep
    the account menu behind a canvas or a custom widget (todoist, canva) were
    reported not_signed_in even though the account had just been created.
    Combine DOM evidence with the URL and a session cookie check.
    """
    script = """
    (() => {
      const q = (s) => document.querySelector(s);
      const body = (document.body && document.body.innerText || '').toLowerCase();

      const hasAccountUi = !!q(
        'a[href*="logout"], a[href*="signout"], a[href*="sign-out"],' +
        'a[href*="/account"], a[href*="/settings"],' +
        'button[aria-label*="Account" i], button[aria-label*="account" i],' +
        'img[alt*="avatar" i], [data-testid*="avatar" i], [data-testid*="user-menu" i],' +
        '[data-testid*="UserMenu" i], [aria-label*="User menu" i],' +
        '[class*="avatar" i], [data-testid*="profile" i]'
      );
      const hasLogoutText = /\\blog\\s*out\\b|\\bsign\\s*out\\b/.test(body);

      // A visible password box means we are still on an auth screen.
      const pw = q('input[type="password"]');
      const pwVisible = !!(pw && pw.offsetParent !== null);
      const authForm = !!q('form[action*="login"], form[action*="signin"], form[action*="signup"]');

      // Authenticated app routes.
      const u = location.href.toLowerCase();
      const appUrl = /(^https?:\\/\\/app\\.)|(\\/app(\\/|$))|\\/dashboard|\\/workspace|\\/home(\\/|$)|\\/projects|\\/inbox|\\/onboarding/.test(u);
      const authUrl = /\\/(login|signin|sign-in|signup|sign-up|register|join)(\\/|$|\\?|#)/.test(u);

      return {
        hasAccountUi, hasLogoutText, pwVisible, authForm, appUrl, authUrl,
        marketing: /get started free|sign up free|start for free|request a demo/.test(body),
      };
    })()
    """
    try:
        info = await page.evaluate(script)
    except Exception:
        return False
    if not isinstance(info, dict):
        return False

    # Still on an auth screen -> definitely not in.
    if info.get("pwVisible") or (info.get("authUrl") and not info.get("hasAccountUi")):
        return False
    if info.get("hasAccountUi") or info.get("hasLogoutText"):
        return True

    # No obvious account chrome: fall back to a real session cookie on an app route.
    if not info.get("appUrl"):
        return False
    try:
        cookies = await page.context.cookies()
    except Exception:
        cookies = []
    for cookie in cookies:
        name = cookie.get("name") or ""
        if _AUTH_COOKIE_SKIP.search(name):
            continue
        if _AUTH_COOKIE_RE.search(name) and len(str(cookie.get("value") or "")) >= 16:
            return True
    return False


def _build_signup_tools(ctx: dict[str, Any]):
    """Register deterministic escape hatches on a browser-use Tools registry."""
    from browser_use.agent.views import ActionResult
    from browser_use.tools.service import Tools

    tools = Tools()
    identity: Identity = ctx["identity"]
    host: str = ctx["host"]
    page_getter = ctx["page_getter"]  # callable () -> page

    def _request_stop(reason: str = "") -> None:
        """Best-effort agent.stop from inside a tool (event-loop may be wedged)."""
        import threading
        import time as _t

        stop = ctx.get("stop_agent")
        if callable(stop):
            try:
                stop()
                print(f"==> stop_agent from tool ({reason})", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"==> stop_agent from tool failed: {exc}", flush=True)

        def _kick() -> None:
            # browser-use can block the event loop after escalate tools, so the
            # asyncio stop_watcher never runs. Re-call stop, then close the
            # Browserbase session to force CDP disconnect and unwedge.
            for i in range(24):
                _t.sleep(0.25)
                if ctx.get("kick_stop"):
                    return
                if not (
                    ctx.get("escalate_requested")
                    or (ctx.get("done") and ctx.get("blocker"))
                ):
                    return
                stop2 = ctx.get("stop_agent")
                if callable(stop2) and i < 6:
                    try:
                        stop2()
                        if i in (0, 2, 5):
                            print(f"==> stop_agent re-kick ({reason})", flush=True)
                    except Exception:
                        pass
                if i == 6 and not ctx.get("unwedge_bb_closed"):
                    sid = ctx.get("bb_session_id")
                    if sid:
                        try:
                            from capability.browserbase_client import close_session

                            close_session(sid)
                            ctx["unwedge_bb_closed"] = True
                            print(
                                f"==> closed Browserbase session {sid} to unwedge after {reason}",
                                flush=True,
                            )
                        except Exception as exc:  # noqa: BLE001
                            print(
                                f"==> BB session close for unwedge failed: {exc}",
                                flush=True,
                            )

                # Cancel agent_task if the loop can still schedule work. If the
                # loop is wedged in a sync/C call, also inject InterruptedError
                # into the main thread so the attempt can exit into antibot retry.
                if i in (8, 12, 16, 20):
                    loop = ctx.get("event_loop")
                    task = ctx.get("agent_task")
                    if loop is not None and task is not None and not task.done():

                        def _cancel(t=task, r=reason, n=i) -> None:
                            if not t.done():
                                t.cancel()
                                print(
                                    f"==> cancelled agent_task from kick "
                                    f"(i={n}, {r})",
                                    flush=True,
                                )

                        try:
                            loop.call_soon_threadsafe(_cancel)
                        except Exception as exc:  # noqa: BLE001
                            print(
                                f"==> agent_task cancel schedule failed: {exc}",
                                flush=True,
                            )

                    if i in (12, 20) and (
                        ctx.get("escalate_requested")
                        or (ctx.get("done") and ctx.get("blocker"))
                    ):
                        main_id = ctx.get("main_thread_id")
                        if main_id:
                            import ctypes

                            try:
                                n_aff = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                                    ctypes.c_ulong(main_id),
                                    ctypes.py_object(AntibotUnwedge),
                                )
                                if n_aff > 1:
                                    ctypes.pythonapi.PyThreadState_SetAsyncExc(
                                        ctypes.c_ulong(main_id), None
                                    )
                                print(
                                    f"==> injected AntibotUnwedge into main "
                                    f"thread (i={i}, {reason}, affected={n_aff})",
                                    flush=True,
                                )
                            except Exception as exc:  # noqa: BLE001
                                print(
                                    f"==> main-thread interrupt failed: {exc}",
                                    flush=True,
                                )

                if i == 22 and ctx.get("escalate_requested") and not ctx.get("kick_stop"):
                    esc_path = os.environ.get("MVP_ANTIBOT_ESCALATE_PATH")
                    if esc_path:
                        try:
                            Path(esc_path).write_text(
                                json.dumps(
                                    {
                                        "escalate_kind": ctx.get("escalate_kind"),
                                        "bb_flags": ctx.get("bb_flags"),
                                    }
                                )
                            )
                        except Exception as exc:  # noqa: BLE001
                            print(f"==> escalate path write failed: {exc}", flush=True)
                    print(
                        f"==> hard-exit 78 for antibot supervisor unwedge ({reason})",
                        flush=True,
                    )
                    os._exit(78)

        threading.Thread(target=_kick, name="antibot-stop-kick", daemon=True).start()


    def _arm_escalate(kind: str, detail: str = "") -> None:
        ctx["escalate_kind"] = kind
        ctx["escalate_requested"] = True
        ctx["escalate_detail"] = detail or ""
        ctx["blocker"] = None
        ctx["done"] = True
        _request_stop(f"escalate:{kind}")


    class ReportBlockedParams(BaseModel):
        reason: str = Field(
            description=(
                "One of: card_required, sso_only, invite_only, waitlist, "
                "captcha_unsolved, rate_limited, unknown"
            )
        )
        detail: str = Field(default="", description="Short human-readable explanation")

    class SignupTipsParams(BaseModel):
        symptom: str = Field(
            default="",
            description=(
                "Short phrase for the current blocker, e.g. 'submit does nothing', "
                "'captcha', 'email already used', 'SSO only'. Empty returns a small "
                "default tip set for this host."
            ),
        )

    class NoteFailureParams(BaseModel):
        symptom: str = Field(description="What failed, in one short phrase")
        detail: str = Field(default="", description="Optional page/context detail")
        mode_id: str = Field(
            default="",
            description="Optional matching tip id from get_signup_tips, if known",
        )

    class EmptyParams(BaseModel):
        pass

    @tools.registry.action(
        "Return the signup identity to use on this product: email, password, "
        "full_name, company, phone. Always use these exact values — never invent them.",
        param_model=EmptyParams,
    )
    async def get_identity(params: EmptyParams):
        payload = {
            "email": identity.email,
            "password": identity.password,
            "full_name": identity.full_name,
            "company": identity.company,
            "phone": identity.phone,
        }
        # Put the FULL payload in long_term_memory — browser-use often surfaces
        # that field to the model more reliably than extracted_content alone.
        # (Previously only the email was remembered → agent looped on get_identity.)
        blob = json.dumps(payload)
        return ActionResult(
            extracted_content=blob,
            include_in_memory=True,
            long_term_memory=f"Signup identity (use exactly): {blob}",
        )

    @tools.registry.action(
        "Wait for a verification CODE emailed to the signup alias. "
        "Call mark_email_requested() first, then this. Returns the code digits.",
        param_model=EmptyParams,
    )
    async def get_email_code(params: EmptyParams):
        # If the agent forgot mark_email_requested, still search recent mail
        # instead of anchoring at "now" (which misses the just-sent message).
        if not ctx.get("email_requested_at"):
            ctx["email_requested_at"] = time.time() - 90
        newer = ctx["email_requested_at"]
        code = await asyncio.to_thread(
            wait_for_signup_code,
            identity.email,
            # Serial runs can afford ~90s; keep under step_timeout (180).
            timeout_s=float(os.environ.get("MVP_SIGNUP_EMAIL_TIMEOUT_S", "90")),
            newer_than=newer,
        )
        if not code:
            return ActionResult(
                error=(
                    "No verification code arrived in email within timeout. "
                    "Click Resend once, call mark_email_requested(), then get_email_code() again."
                ),
                include_in_memory=True,
            )
        # The literal code MUST be in long_term_memory. extracted_content is
        # trimmed from history after a few steps, and the agent then invents a
        # placeholder (observed: it typed "123456").
        return ActionResult(
            extracted_content=code,
            include_in_memory=True,
            long_term_memory=f"Email verification code (type exactly): {code}",
        )

    @tools.registry.action(
        "Wait for a confirmation / magic LINK emailed to the signup alias. "
        "Call mark_email_requested() first. Returns the URL — open with go_to_url.",
        param_model=EmptyParams,
    )
    async def get_email_link(params: EmptyParams):
        if not ctx.get("email_requested_at"):
            ctx["email_requested_at"] = time.time() - 90
        newer = ctx["email_requested_at"]
        link = await asyncio.to_thread(
            wait_for_signup_link,
            identity.email,
            host=host,
            timeout_s=float(os.environ.get("MVP_SIGNUP_EMAIL_TIMEOUT_S", "90")),
            newer_than=newer,
        )
        if not link:
            return ActionResult(
                error=(
                    "No confirmation link arrived in email within timeout. "
                    "Click Resend once, call mark_email_requested(), then get_email_link() again."
                ),
                include_in_memory=True,
            )
        return ActionResult(
            extracted_content=link,
            include_in_memory=True,
            long_term_memory=f"Email confirmation link for {host} (open exactly): {link}",
        )

    @tools.registry.action(
        "Mark that an email verification was just requested (starts the IMAP clock). "
        "Call immediately after clicking 'Send code' / 'Verify email' / 'Continue'.",
        param_model=EmptyParams,
    )
    async def mark_email_requested(params: EmptyParams):
        ctx["email_requested_at"] = time.time()
        return ActionResult(
            extracted_content="ok",
            include_in_memory=True,
            long_term_memory="Email verification requested; waiting for inbox",
        )

    @tools.registry.action(
        "Lease a phone number (or reuse the owner phone) and wait for an SMS "
        "verification code. Returns JSON with phone and code.",
        param_model=EmptyParams,
    )
    async def get_sms_code(params: EmptyParams):
        number: Number | None = ctx.get("sms_number")
        try:
            if number is None:
                number = await asyncio.to_thread(lease_number, host)
                ctx["sms_number"] = number
                ctx["sms_requested_at"] = time.time()
            code = await asyncio.to_thread(
                wait_for_sms,
                number,
                timeout_s=float(os.environ.get("MVP_SIGNUP_SMS_TIMEOUT_S", "90")),
                newer_than=ctx.get("sms_requested_at") or time.time(),
            )
        except Exception as exc:
            return ActionResult(error=f"SMS failed: {exc}", include_in_memory=True)
        if not code:
            return ActionResult(
                error="No SMS verification code arrived within timeout",
                include_in_memory=True,
            )
        return ActionResult(
            extracted_content=json.dumps({"phone": number.phone, "code": code}),
            include_in_memory=True,
            long_term_memory=f"SMS code for {number.phone} (type exactly): {code}",
        )

    @tools.registry.action(
        "Return a TOTP authenticator code if the vault has a totp_secret for this host. "
        "Usually not needed during first-time signup.",
        param_model=EmptyParams,
    )
    async def get_totp_code(params: EmptyParams):
        from mvp.credentials import credentials_for_url

        creds = credentials_for_url(f"https://{host}/") or {}
        code = totp_code(creds.get("totp_secret"))
        if not code:
            return ActionResult(
                error="No totp_secret available for this host",
                include_in_memory=True,
            )
        return ActionResult(extracted_content=code, include_in_memory=True)

    @tools.registry.action(
        "Attempt to solve a CAPTCHA on the current page (solver API, then human ping). "
        "Call when a captcha/checkbox/challenge is blocking progress. "
        "If Browserbase captcha solve is still OFF, call request_antibot_escalation(kind=captcha) "
        "instead of looping. If this returns an error after captcha is ON, call "
        "report_blocked(captcha_unsolved) — do not wait/loop.",
        param_model=EmptyParams,
    )
    async def solve_captcha(params: EmptyParams, browser_session):  # noqa: ANN001 — injected special arg
        bb_flags = ctx.get("bb_flags") or {}
        # Cheap session: do not burn CapSolver/human quota until BB captcha is armed.
        if ctx.get("use_bb") and not bb_flags.get("solve_captchas"):
            _arm_escalate("captcha", "solve_captcha:escalate")
            return ActionResult(
                is_done=True,
                success=False,
                error=(
                    "Browserbase captcha solve is OFF (quota save). "
                    "Escalation armed — this attempt will restart with solve_captchas. "
                    "Do not wait-loop on the challenge."
                ),
                extracted_content=json.dumps(
                    {"escalate": "captcha", "bb_flags": bb_flags}
                ),
                include_in_memory=True,
                long_term_memory=(
                    "Captcha hit on cheap session — antibot escalate to solve_captchas."
                ),
            )
        page = None
        # Prefer the live browser-use page over the stale Playwright handle.
        try:
            page = await browser_session.get_current_page()
        except Exception:
            try:
                get_pages = getattr(browser_session, "get_pages", None)
                if callable(get_pages):
                    pages = await get_pages()
                    page = pages[0] if pages else None
            except Exception:
                page = None
        if page is None:
            page = page_getter()
        if page is None:
            ctx["blocker"] = "captcha_unsolved"
            return ActionResult(
                error="No active page for captcha; call report_blocked(captcha_unsolved)",
                include_in_memory=True,
            )
        result = await solve_captcha_on_page(page)
        if result.get("ok"):
            return ActionResult(
                extracted_content=json.dumps(result),
                include_in_memory=True,
                long_term_memory=f"CAPTCHA solved via {result.get('method')}",
            )
        # Allow exactly one retry: scoring-based challenges often pass on a
        # second look a few seconds later. Only the second failure is terminal.
        attempts = int(ctx.get("captcha_attempts") or 0) + 1
        ctx["captcha_attempts"] = attempts
        if attempts < 2:
            return ActionResult(
                error=(
                    f"CAPTCHA not cleared yet ({result.get('method')}). "
                    "Wait ~5s, then call solve_captcha() ONE more time. "
                    "If it fails again: if proxies are still OFF call "
                    "request_antibot_escalation(kind=captcha); else "
                    "report_blocked(captcha_unsolved)."
                ),
                include_in_memory=True,
            )
        # Captcha still failing with BB solve on — escalate proxies/Verified once
        # before hard-failing, when those flags are still off.
        if ctx.get("use_bb") and (
            not bb_flags.get("proxies") or not bb_flags.get("advanced_stealth")
        ):
            _arm_escalate("captcha", "solve_captcha:escalate")
            return ActionResult(
                is_done=True,
                success=False,
                error=(
                    f"CAPTCHA unsolved after {attempts} attempts with captcha solve ON. "
                    "Arming further antibot escalate (proxies/Verified). "
                    "Do not wait-loop."
                ),
                extracted_content=json.dumps(
                    {"escalate": "captcha", "bb_flags": bb_flags, "result": result}
                ),
                include_in_memory=True,
                long_term_memory="Captcha still blocked — escalate antibot further.",
            )
        ctx["blocker"] = "captcha_unsolved"
        return ActionResult(
            error=(
                f"CAPTCHA unsolved after {attempts} attempts ({result}). "
                "Call report_blocked with reason captcha_unsolved now — do not retry wait loops."
            ),
            include_in_memory=True,
        )

    class EscalateAntibotParams(BaseModel):
        kind: str = Field(
            description=(
                "What you hit: captcha (reCAPTCHA/Turnstile/Cloudflare challenge), "
                "rate_limit ('try again later' / too many requests), "
                "ip_block ('whoa there' / blocked from this IP), "
                "bot_block (persistent fingerprint / bot wall after captcha+proxy)."
            )
        )
        detail: str = Field(
            default="",
            description="Short page text / symptom that justified the escalate",
        )

    @tools.registry.action(
        "Request a Browserbase antibot upgrade and stop this attempt. "
        "Use ONLY when you observe a real blocker — do not call on every signup. "
        "kind=captcha → enable Browserbase captcha solve (then proxies/Verified if needed). "
        "kind=rate_limit or ip_block → enable residential proxies. "
        "kind=bot_block → proxies + captcha + Verified/advanced stealth. "
        "The outer runner restarts once with those flags. Prefer this over burning "
        "steps in wait loops. Soft product gates (card/SSO/invite/waitlist) use "
        "report_blocked instead.",
        param_model=EscalateAntibotParams,
    )
    async def request_antibot_escalation(params: EscalateAntibotParams):
        kind = (params.kind or "").strip().lower().replace("-", "_")
        aliases = {
            "captcha_unsolved": "captcha",
            "rate_limited": "rate_limit",
            "ip_blocked": "ip_block",
            "fingerprint": "bot_block",
        }
        kind = aliases.get(kind, kind)
        if kind not in _ANTIBOT_KINDS:
            return ActionResult(
                error=(
                    f"Unknown escalate kind {params.kind!r}. "
                    "Use captcha | rate_limit | ip_block | bot_block."
                ),
                include_in_memory=True,
            )
        bb_flags = ctx.get("bb_flags") or {}
        nxt = _next_antibot_flags(bb_flags, kind)
        if nxt is None:
            mapped = {
                "captcha": "captcha_unsolved",
                "rate_limit": "rate_limited",
                "ip_block": "rate_limited",
                "bot_block": "captcha_unsolved",
            }.get(kind, "unknown")
            ctx["blocker"] = mapped
            ctx["blocker_detail"] = params.detail or f"escalate_ceiling:{kind}"
            ctx["done"] = True
            _request_stop(f"ceiling:{kind}")
            return ActionResult(
                is_done=True,
                success=False,
                error=(
                    f"Antibot already at max for {kind} (flags={bb_flags}). "
                    f"Call report_blocked({mapped}) — cannot escalate further."
                ),
                extracted_content=json.dumps(
                    {"escalate": None, "ceiling": True, "bb_flags": bb_flags}
                ),
                include_in_memory=True,
                long_term_memory=f"Antibot ceiling for {kind}; treat as blocked.",
            )
        _arm_escalate(kind, params.detail or "")
        try:
            record_observation(
                host=host,
                symptom=f"escalate:{kind}",
                detail=params.detail or "",
                mode_id=None,
                source="request_antibot_escalation",
            )
        except Exception:
            pass
        return ActionResult(
            is_done=True,
            success=False,
            extracted_content=json.dumps(
                {
                    "escalate": kind,
                    "from_flags": bb_flags,
                    "to_flags": nxt,
                    "detail": params.detail,
                }
            ),
            long_term_memory=(
                f"Antibot escalate requested ({kind}) → {nxt}. Stopping attempt to restart."
            ),
            include_in_memory=True,
        )

    @tools.registry.action(
        "Look up short tips for a common signup failure mode. Call when stuck "
        "(same click twice with no progress, captcha, OTP, SSO, etc.). "
        "Pass a short symptom phrase — do not dump the whole catalog into memory.",
        param_model=SignupTipsParams,
    )
    async def get_signup_tips(params: SignupTipsParams):
        tip_text = lookup_tips(host=host, query=params.symptom or "", limit=5)
        return ActionResult(
            extracted_content=tip_text,
            include_in_memory=True,
            long_term_memory=tip_text[:500],
        )

    @tools.registry.action(
        "Record a new signup failure observation for later curation into the "
        "shared failure-modes JSON. Call when you hit a novel blocker or before "
        "report_blocked. Does not stop the run.",
        param_model=NoteFailureParams,
    )
    async def note_signup_failure(params: NoteFailureParams):
        try:
            obs = record_observation(
                host=host,
                symptom=params.symptom,
                detail=params.detail or "",
                mode_id=params.mode_id or None,
                source="agent",
            )
        except ValueError as exc:
            return ActionResult(error=str(exc), include_in_memory=True)
        return ActionResult(
            extracted_content=json.dumps(obs),
            include_in_memory=True,
            long_term_memory=f"Recorded signup failure observation: {params.symptom}",
        )

    @tools.registry.action(
        "Stop signup — the product requires something we cannot automate "
        "(card_required, sso_only, invite_only, waitlist, captcha_unsolved, "
        "rate_limited, unknown). For captcha/IP/rate walls when Browserbase "
        "antibot is still OFF, prefer request_antibot_escalation first. "
        "Call this instead of looping when blocked.",
        param_model=ReportBlockedParams,
    )
    async def report_blocked(params: ReportBlockedParams):
        reason = (params.reason or "unknown").strip().lower()
        if reason not in BLOCK_REASONS:
            reason = "unknown"
        bb_flags = ctx.get("bb_flags") or {}
        if ctx.get("use_bb"):
            if reason == "captcha_unsolved" and _next_antibot_flags(bb_flags, "captcha"):
                _arm_escalate("captcha", params.detail or "report_blocked:captcha_unsolved")
                return ActionResult(
                    is_done=True,
                    success=False,
                    extracted_content=json.dumps(
                        {"escalate": "captcha", "from_report_blocked": True}
                    ),
                    long_term_memory=(
                        "captcha_unsolved remapped to antibot escalate "
                        "(captcha still off or further ladder available)."
                    ),
                    include_in_memory=True,
                )
            if reason == "rate_limited" and _next_antibot_flags(bb_flags, "rate_limit"):
                _arm_escalate("rate_limit", params.detail or "report_blocked:rate_limited")
                return ActionResult(
                    is_done=True,
                    success=False,
                    extracted_content=json.dumps(
                        {"escalate": "rate_limit", "from_report_blocked": True}
                    ),
                    long_term_memory=(
                        "rate_limited remapped to antibot escalate (proxies still available)."
                    ),
                    include_in_memory=True,
                )
        ctx["blocker"] = reason
        ctx["blocker_detail"] = params.detail or ""
        ctx["done"] = True
        _request_stop(f"blocked:{reason}")
        try:
            record_observation(
                host=host,
                symptom=f"blocked:{reason}",
                detail=params.detail or "",
                mode_id=None,
                source="report_blocked",
            )
        except Exception:
            pass
        return ActionResult(
            is_done=True,
            success=False,
            extracted_content=json.dumps({"blocked": reason, "detail": params.detail}),
            long_term_memory=f"Signup blocked: {reason}",
            include_in_memory=True,
        )

    return tools


async def sign_up(
    url: str,
    *,
    identity: Identity | None = None,
    timeout_s: float = 900.0,
    headed: bool = True,
    max_steps: int | None = None,
    cdp_port: int | None = None,
) -> dict[str, Any]:
    """Create an account on ``url`` and persist the signed-in Chrome profile.

    Browserbase sessions start cheap (no proxies/captcha/Verified). When the
    agent hits captcha or IP/rate walls it calls ``request_antibot_escalation``
    (or ``report_blocked`` / ``solve_captcha`` remaps) and we retry with the
    matching flags — never enable paid antibot on every run.
    """
    from browser_use import Agent, ChatGoogle
    from browser_use.browser.profile import BrowserProfile
    from auth import vertex_credentials
    from capability import location_for
    from config import GCP_PROJECT, MODEL
    from playwright.async_api import async_playwright

    host = host_for_url(url)
    identity = identity or provision_identity(url)
    # identities.json travels between machines (laptop -> VM) and stores an
    # absolute profile_dir. Honour it only when it belongs to this checkout,
    # otherwise a macOS path is replayed on Linux and mkdir dies on /Users.
    profile = PRODUCT_PROFILES / safe_host(host)
    stored = (identity.profile_dir or "").strip()
    if stored:
        candidate = Path(stored)
        if candidate.is_absolute() and candidate.is_relative_to(ROOT):
            profile = candidate
        elif not candidate.is_absolute():
            profile = ROOT / candidate
    profile.mkdir(parents=True, exist_ok=True)
    step_dir = STEP_DIR_ROOT / safe_host(host)
    step_dir.mkdir(parents=True, exist_ok=True)
    port = int(cdp_port or os.environ.get("MVP_SIGNUP_CDP_PORT") or CDP_PORT_DEFAULT)

    start_url = url if urlparse(url).scheme else f"https://{url}"
    host_key = (urlparse(start_url).hostname or host or "").lower()
    if host_key.startswith("www."):
        host_key = host_key[4:]
    if host_key in SIGNUP_START and not re.search(
        r"/(signup|sign-up|sign_up|register|join)(/|$|#)", start_url, re.I
    ):
        start_url = SIGNUP_START[host_key]

    max_steps = max_steps or int(os.environ.get("MVP_SIGNUP_MAX_STEPS", "40"))
    use_bb = _signup_uses_browserbase()
    max_antibot = 1
    if use_bb:
        # Captcha ladder needs 4 attempts: cheap → captcha → proxies → Verified.
        max_antibot = max(1, int(os.environ.get("MVP_SIGNUP_ANTIBOT_MAX_ATTEMPTS", "4")))
    bb_flags = _cheap_bb_flags()
    _flags_json = os.environ.get("MVP_BB_FLAGS_JSON", "").strip()
    if _flags_json:
        try:
            bb_flags = {**bb_flags, **json.loads(_flags_json)}
        except Exception:
            pass

    antibot_log: list[dict[str, Any]] = []
    final_result: dict[str, Any] | None = None

    for attempt_i in range(max_antibot):
        proc: subprocess.Popen | None = None
        bb_session = None
        cdp_url = f"http://127.0.0.1:{port}"
        result: dict[str, Any] = {
            "ok": False,
            "host": host,
            "email": identity.email,
            "profile_dir": str(profile),
            "actions": [],
            "backend": "local_chrome",
            "antibot_attempt": attempt_i,
            "browserbase_flags": dict(bb_flags) if use_bb else None,
        }

        if use_bb:
            from capability.browserbase_client import close_session

            # Cheap-first; escalated flags come from a prior attempt.
            bb_session, bb_flags = await asyncio.to_thread(
                _create_signup_browserbase_session, bb_flags
            )
            cdp_url = bb_session.connect_url
            result["backend"] = "browserbase"
            result["browserbase_session_url"] = bb_session.session_url
            result["browserbase_flags"] = bb_flags
            print(
                f"Browserbase session={bb_session.id} url={bb_session.session_url} "
                f"flags={bb_flags} attempt={attempt_i}",
                flush=True,
                file=__import__("sys").stderr,
            )
        else:
            proc = _launch_chrome(start_url, profile, headed=headed, cdp_port=port)
            result["backend"] = "local_chrome"
            print(
                f"Chrome pid={proc.pid} profile={profile} port={port}",
                flush=True,
                file=__import__("sys").stderr,
            )

        ctx: dict[str, Any] = {
            "bb_flags": dict(bb_flags) if use_bb else {},
            "identity": identity,
            "host": host,
            "page_getter": lambda: None,
            "blocker": None,
            "blocker_detail": None,
            "done": False,
            "sms_number": None,
            "use_bb": use_bb,
            "bb_flags": dict(bb_flags) if use_bb else {},
            "escalate_requested": False,
            "escalate_kind": None,
            "escalate_detail": None,
            "captcha_attempts": 0,
            "bb_session_id": getattr(bb_session, "id", None) if bb_session else None,
            "unwedge_bb_closed": False,
        }

        try:
            async with async_playwright() as p:
                browser = None
                deadline = time.time() + min(60.0, timeout_s)
                while browser is None and time.time() < deadline:
                    try:
                        browser = await p.chromium.connect_over_cdp(cdp_url)
                    except Exception:
                        await asyncio.sleep(1)
                if browser is None:
                    result["reason"] = "cdp_unreachable"
                    return result

                pw_ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = pw_ctx.pages[0] if pw_ctx.pages else await pw_ctx.new_page()
                # Browserbase starts on about:blank — land on the signup URL ourselves.
                if use_bb:
                    try:
                        await page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
                    except Exception as exc:
                        result["reason"] = f"navigate_failed:{type(exc).__name__}"
                        result["detail"] = str(exc)[:200]
                        return result
                ctx["page_getter"] = lambda: page

                # Already signed in from a previous run?
                if await _looks_signed_in(page):
                    state = await pw_ctx.storage_state()
                    SITE_STATES.mkdir(parents=True, exist_ok=True)
                    site_state_path(host).write_text(json.dumps(state, indent=2))
                    update_identity(url, status="signed_up", blocker=None, profile_dir=str(profile))
                    result.update({"ok": True, "reason": "already_signed_in"})
                    return result

                tools = _build_signup_tools(ctx)
                # Always Gemini 2.5 Flash via Vertex.
                model = (os.environ.get("MVP_SIGNUP_MODEL") or MODEL or "").strip()
                llm = ChatGoogle(
                    model=model,
                    vertexai=True,
                    credentials=vertex_credentials(),
                    project=GCP_PROJECT,
                    location=location_for(model),
                    temperature=0,
                )
                # Attach to the already-running Chrome via CDP so the persistent
                # profile is the one we launched (not a throwaway browser-use profile).
                bu_profile = BrowserProfile(
                    cdp_url=cdp_url,
                    is_local=False,
                    viewport={"width": 1440, "height": 900},
                    disable_security=True,
                    highlight_elements=False,
                    captcha_solver=bool((ctx.get("bb_flags") or {}).get("solve_captchas"))
                    or (
                        os.environ.get("MVP_CAPTCHA_SOLVER", "").lower()
                        in {"1", "true", "yes"}
                    ),
                )
                id_blob = json.dumps(
                    {
                        "email": identity.email,
                        "password": identity.password,
                        "full_name": identity.full_name,
                        "company": identity.company,
                        "phone": identity.phone,
                    }
                )
                task = (
                    f"Create a free account on {start_url} for product host {host}.\n"
                    f"IDENTITY (use these exact values; do not invent credentials):\n{id_blob}\n"
                    f"You may call get_identity() once to confirm — do NOT call it repeatedly.\n"
                    f"Flow:\n"
                    f"1. You should already be on a signup page. If not, open Sign up / Create account "
                    f"(not Sign in).\n"
                    f"2. Fill the registration form with the IDENTITY values above.\n"
                    f"3. Accept terms if required. Skip optional marketing checkboxes.\n"
                    f"4. If email verification is required: call mark_email_requested(), "
                    f"then get_email_code() or get_email_link() and complete verification.\n"
                    f"   NEVER invent a verification code. Type the exact digits the tool "
                    f"returned. If you cannot see a real code, call the tool again — do not "
                    f"guess placeholders like 123456.\n"
                    f"5. If SMS is required: call get_sms_code() and enter the code.\n"
                    f"6. ANTIBOT (conditional — do NOT escalate preemptively):\n"
                    f"   - CAPTCHA/Turnstile/Cloudflare visible: call solve_captcha() once "
                    f"(cheap sessions auto-escalate captcha; or call "
                    f"request_antibot_escalation(kind=captcha)).\n"
                    f"   - 'try again later' / soft rate limit after email Continue: wait ~5s, "
                    f"retry email once, then request_antibot_escalation(kind=rate_limit).\n"
                    f"   - IP wall ('whoa there', 'too many requests from your IP'): "
                    f"request_antibot_escalation(kind=ip_block). Do not solve_captcha-loop.\n"
                    f"   - Persistent bot/fingerprint wall after captcha+proxy: "
                    f"request_antibot_escalation(kind=bot_block).\n"
                    f"   Only after escalate ceiling: report_blocked(captcha_unsolved|rate_limited).\n"
                    f"7. Skip or dismiss onboarding tours once the account exists.\n"
                    f"8. Stop when you are clearly signed in (account menu / dashboard / logout).\n"
                    f"If the product requires a credit card, SSO-only, invite-only access, "
                    f"or a waitlist, call report_blocked with the matching reason.\n"
                    f"Do NOT try to pay.\n"
                    f"EMAIL PATH ONLY: never click Google / Microsoft / Apple / GitHub / SSO. "
                    f"The IDENTITY email is a plus-alias — SSO will fail and burning steps creating "
                    f"IdP accounts is forbidden. Do not pivot to SSO.\n"
                    f"Browserbase antibot flags for THIS attempt: "
                    f"{json.dumps(ctx.get('bb_flags') or {})} "
                    f"(cheap by default — escalate only when hit).\n"
                    f"If the same action fails twice with no progress, call "
                    f"get_signup_tips(symptom=...) once, apply a matching tip, then continue. "
                    f"For a novel blocker, call note_signup_failure before report_blocked."
                )
                # Used to exercise the phone→ntfy SMS path end-to-end. Optional phone
                # prompts (Zoom "Skip" / "No thanks") otherwise get dismissed and never
                # produce a text — which is correct for normal signup, wrong for a relay test.
                if os.environ.get("MVP_SIGNUP_REQUIRE_SMS", "").strip().lower() in {
                    "1",
                    "true",
                    "yes",
                }:
                    phone = identity.phone or "the vault phone"
                    task += (
                        f"\n\nCRITICAL — SMS REQUIRED FOR THIS RUN:\n"
                        f"- You MUST enter phone number {phone} and complete SMS verification "
                        f"via get_sms_code().\n"
                        f"- Do NOT click Skip / Not now / No thanks on any phone or text prompts.\n"
                        f"- If the product offers optional phone linking, take it and finish SMS OTP.\n"
                        f"- Do not call done() until SMS verification has succeeded."
                    )
                agent = Agent(
                    task=task,
                    llm=llm,
                    browser_profile=bu_profile,
                    tools=tools,
                    use_vision=True,
                    use_judge=False,
                    max_actions_per_step=2,
                    calculate_cost=True,
                    file_system_path=str(step_dir),
                    save_conversation_path=str(step_dir / "conversation"),
                    extend_system_message=(
                        "You are signing up for a product so usability agents can study the "
                        "authenticated experience. Use email/password only — never Google, "
                        "Microsoft, Apple, or GitHub SSO (the identity is a plus-alias). "
                        "Be decisive; do not loop on the same form. "
                        "Recognize antibot events and escalate ONLY when hit: captcha → "
                        "request_antibot_escalation(captcha) or solve_captcha; IP/'whoa there' → "
                        "ip_block; 'try again later' after one email retry → rate_limit. "
                        "Do not request escalation preemptively. Soft product gates "
                        "(card, SSO-only, invite, waitlist) use report_blocked. If an AUTO TIP "
                        "follow-up appears, apply it immediately; else on repeated failure call "
                        "get_signup_tips once."
                    ),
                )
                ctx["stop_agent"] = agent.stop


                # Flash rarely calls get_signup_tips on its own. When browser-use
                # reports loop/stagnation, inject host-matched tips as a follow-up
                # task (still from the JSON catalog — not baked into the main prompt).
                tip_injects = {"count": 0}
                # Mid-run cookie snapshots: browser-use closes its CDP view on done(),
                # so a post-run storage_state() often fails with "browser has been closed".
                live_state: dict[str, Any] = {"state": None}

                async def _snapshot_cookies(label: str) -> None:
                    try:
                        snap = await pw_ctx.storage_state()
                    except Exception as exc:  # noqa: BLE001
                        print(f"==> cookie snapshot ({label}) missed: {exc}"[:200], flush=True)
                        return
                    live_state["state"] = snap
                    try:
                        SITE_STATES.mkdir(parents=True, exist_ok=True)
                        site_state_path(host).write_text(json.dumps(snap, indent=2))
                    except Exception:
                        pass

                async def _on_step_end(ag) -> None:  # noqa: ANN001
                    # Always try to persist cookies while the Browserbase session lives.
                    await _snapshot_cookies("step")

                    # If escalate/block tools already armed, force-stop so agent.run
                    # cannot hang after terminates_sequence (observed on Notion/Reddit).
                    if ctx.get("escalate_requested") or (
                        ctx.get("done") and ctx.get("blocker")
                    ):
                        try:
                            ag.stop()
                        except Exception as exc:  # noqa: BLE001
                            print(f"==> agent.stop on escalate missed: {exc}", flush=True)
                        return

                    detector = getattr(getattr(ag, "state", None), "loop_detector", None)
                    if detector is None:
                        return
                    sig = loop_detector_signal(detector)
                    if not should_inject_loop_tips(
                        repetition=sig["repetition"],
                        stagnation=sig["stagnation"],
                        inject_count=tip_injects["count"],
                    ):
                        return
                    followup = loop_tips_followup(
                        host=host,
                        repetition=sig["repetition"],
                        stagnation=sig["stagnation"],
                        inject_count=tip_injects["count"],
                    )
                    tip_injects["count"] += 1
                    print(
                        f"==> auto-injected signup tips "
                        f"(n={tip_injects['count']} stagnation={sig['stagnation']} "
                        f"repetition={sig['repetition']})",
                        flush=True,
                    )
                    try:
                        ag.add_new_task(followup)
                    except Exception as exc:  # noqa: BLE001
                        print(f"==> tip inject failed: {exc}", flush=True)
                        return
                    try:
                        record_observation(
                            host=host,
                            symptom="auto_inject_loop_tips",
                            detail=(
                                f"stagnation={sig['stagnation']} "
                                f"repetition={sig['repetition']} "
                                f"inject={tip_injects['count']}"
                            ),
                            mode_id=None,
                            source="loop_auto_inject",
                        )
                    except Exception:
                        pass

                history = None
                agent_task = asyncio.create_task(
                    agent.run(max_steps=max_steps, on_step_end=_on_step_end)
                )
                ctx["agent_task"] = agent_task
                ctx["event_loop"] = asyncio.get_running_loop()
                import threading as _threading

                ctx["main_thread_id"] = _threading.get_ident()

                async def _force_stop_if_armed() -> bool:
                    """Return True once escalate/block is armed and stop was requested.

                    browser-use sometimes never returns from agent.run after
                    request_antibot_escalation (terminates_sequence + is_done) —
                    especially when paired with another action in the same step.
                    Poll ctx (set inside the tool) and force-stop so the outer
                    antibot retry loop can resume.
                    """
                    while not agent_task.done():
                        if ctx.get("escalate_requested") or (
                            ctx.get("done") and ctx.get("blocker")
                        ):
                            print(
                                "==> agent stop armed "
                                f"escalate={ctx.get('escalate_kind')} "
                                f"blocker={ctx.get('blocker')}",
                                flush=True,
                            )
                            try:
                                agent.stop()
                            except Exception as exc:  # noqa: BLE001
                                print(f"==> agent.stop failed: {exc}", flush=True)
                            try:
                                await asyncio.wait_for(
                                    asyncio.shield(agent_task), timeout=2.0
                                )
                            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                                pass
                            if not agent_task.done():
                                agent_task.cancel()
                                try:
                                    await asyncio.wait_for(agent_task, timeout=2.0)
                                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                                    pass
                            return True
                        await asyncio.sleep(0.25)
                    return False

                stop_watcher = asyncio.create_task(_force_stop_if_armed())
                try:
                    done, _pending = await asyncio.wait(
                        {agent_task, stop_watcher},
                        return_when=asyncio.FIRST_COMPLETED,
                        timeout=timeout_s,
                    )
                    if not done:
                        result["reason"] = "timeout"
                        try:
                            agent.stop()
                        except Exception:
                            pass
                        if not agent_task.done():
                            agent_task.cancel()
                            try:
                                await agent_task
                            except (asyncio.CancelledError, Exception):
                                pass
                    elif agent_task in done:
                        try:
                            history = agent_task.result()
                        except Exception as exc:  # noqa: BLE001
                            result["reason"] = (
                                f"agent_error:{type(exc).__name__}:{exc}"[:300]
                            )
                    else:
                        # Escalate/block armed — ensure agent_task is finished.
                        if not agent_task.done():
                            try:
                                agent.stop()
                            except Exception:
                                pass
                            agent_task.cancel()
                            try:
                                await agent_task
                            except (asyncio.CancelledError, Exception):
                                pass
                        if ctx.get("escalate_requested"):
                            result["reason"] = result.get("reason") or "antibot_escalate"
                            result["escalate_kind"] = ctx.get("escalate_kind")
                            ctx["kick_stop"] = True
                except AntibotUnwedge:
                    # Kick thread unwedged a stuck agent.run after escalate.
                    print("==> main thread AntibotUnwedge to unwedge escalate", flush=True)
                    ctx["kick_stop"] = True
                    if not agent_task.done():
                        agent_task.cancel()
                        try:
                            await agent_task
                        except (asyncio.CancelledError, Exception):
                            pass
                    if ctx.get("escalate_requested"):
                        result["reason"] = result.get("reason") or "antibot_escalate"
                        result["escalate_kind"] = ctx.get("escalate_kind")
                except Exception as exc:
                    result["reason"] = f"agent_error:{type(exc).__name__}:{exc}"[:300]
                    if not agent_task.done():
                        agent_task.cancel()
                        try:
                            await agent_task
                        except (asyncio.CancelledError, Exception):
                            pass
                finally:
                    if not stop_watcher.done():
                        stop_watcher.cancel()
                        try:
                            await stop_watcher
                        except (asyncio.CancelledError, Exception):
                            pass

                # Refresh page handle after agent activity.
                try:
                    page = pw_ctx.pages[0] if pw_ctx.pages else page
                    ctx["page_getter"] = lambda: page
                except Exception:
                    pass

                try:
                    await page.screenshot(path=str(step_dir / "final.png"), full_page=False)
                except Exception:
                    pass

                # Prefer a final snapshot; fall back to the last mid-run snapshot when
                # browser-use already closed the page (common with Browserbase).
                state: dict[str, Any] | None = live_state.get("state")
                try:
                    state = await pw_ctx.storage_state()
                    live_state["state"] = state
                    SITE_STATES.mkdir(parents=True, exist_ok=True)
                    site_state_path(host).write_text(json.dumps(state, indent=2))
                except Exception as exc:
                    result["state_error"] = str(exc)[:200]
                    if state is not None:
                        result["state_fallback"] = "mid_run_snapshot"
                        try:
                            SITE_STATES.mkdir(parents=True, exist_ok=True)
                            site_state_path(host).write_text(json.dumps(state, indent=2))
                        except Exception:
                            pass

                # Onboarding often ends on a "Getting ready…" splash that redirects a
                # few seconds later, so a single probe reports a fresh account as
                # not_signed_in. Re-probe for a short window before giving up.
                # Skip settle when escalating — we are about to tear down and retry.
                signed = False
                if ctx.get("escalate_requested"):
                    settle_deadline = time.time()
                else:
                    settle_deadline = time.time() + float(
                        os.environ.get("MVP_SIGNUP_SETTLE_S", "30")
                    )
                while True:
                    try:
                        signed = await verify_signed_in(page, host)
                    except Exception:
                        signed = False
                    if signed or time.time() >= settle_deadline:
                        break
                    await asyncio.sleep(3)

                if not signed and state is not None:
                    # Cookie-jar fallback: SPA chrome is flaky right after signup.
                    signed = _storage_state_looks_authed(state, host)
                    if signed:
                        result["signed_via"] = "storage_state"

                # Agent claimed success and we held host cookies from mid-run.
                if (
                    not signed
                    and state is not None
                    and history is not None
                    and getattr(history, "is_successful", None)
                ):
                    try:
                        claimed = bool(history.is_successful())
                    except Exception:
                        claimed = False
                    if claimed and (state.get("cookies") or []):
                        signed = True
                        result["signed_via"] = "agent_success_plus_cookies"

                if ctx.get("escalate_requested") and not signed:
                    # Fall through to finally + outer loop for a flagged retry.
                    result.update(
                        {
                            "ok": False,
                            "reason": "antibot_escalate",
                            "escalate_kind": ctx.get("escalate_kind"),
                            "detail": ctx.get("escalate_detail"),
                        }
                    )
                elif ctx.get("blocker"):
                    update_identity(
                        url,
                        status="blocked",
                        blocker=ctx["blocker"],
                        profile_dir=str(profile),
                    )
                    result.update(
                        {
                            "ok": False,
                            "reason": ctx["blocker"],
                            "detail": ctx.get("blocker_detail"),
                        }
                    )
                elif signed:
                    update_identity(
                        url,
                        status="signed_up",
                        blocker=None,
                        profile_dir=str(profile),
                    )
                    result.update({"ok": True, "reason": "signed_up"})
                else:
                    result["reason"] = result.get("reason") or "not_signed_in"
                    if history is not None:
                        try:
                            result["steps"] = getattr(
                                history, "number_of_steps", lambda: None
                            )()
                        except Exception:
                            pass
                    update_identity(
                        url,
                        status="provisioned",
                        blocker=result.get("reason"),
                        profile_dir=str(profile),
                    )
        finally:
            number = ctx.get("sms_number")
            if number is not None:
                try:
                    await asyncio.to_thread(release, number)
                except Exception:
                    pass
            if bb_session is not None:
                try:
                    from capability.browserbase_client import close_session

                    await asyncio.to_thread(close_session, bb_session.id)
                except Exception:
                    pass
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass


        antibot_log.append(
            {
                "attempt": attempt_i,
                "flags": dict(result.get("browserbase_flags") or {}),
                "reason": result.get("reason"),
                "escalate_kind": result.get("escalate_kind") or ctx.get("escalate_kind"),
                "ok": result.get("ok"),
            }
        )
        result["antibot_log"] = list(antibot_log)
        final_result = result

        if result.get("ok"):
            break
        # Infra / already-done returns exit sign_up via `return result` above.
        reason = result.get("reason")
        if reason in _HARD_BLOCK_REASONS:
            break
        if not use_bb:
            break

        kind = (
            result.get("escalate_kind")
            or ctx.get("escalate_kind")
            or (
                "captcha"
                if reason == "captcha_unsolved"
                else "rate_limit"
                if reason == "rate_limited"
                else None
            )
        )
        if reason == "unknown":
            detail_l = (result.get("detail") or "").lower()
            if any(
                s in detail_l
                for s in ("whoa there", "too many requests", "ip rate", "pardner")
            ):
                kind = kind or "ip_block"
            elif any(s in detail_l for s in ("try again later", "rate limit")):
                kind = kind or "rate_limit"

        if not kind and reason != "antibot_escalate":
            break

        nxt = _next_antibot_flags(bb_flags, kind or "captcha")
        if nxt is None:
            if reason == "antibot_escalate":
                mapped = {
                    "captcha": "captcha_unsolved",
                    "rate_limit": "rate_limited",
                    "ip_block": "rate_limited",
                    "bot_block": "captcha_unsolved",
                }.get((kind or "captcha"), "unknown")
                update_identity(
                    url, status="blocked", blocker=mapped, profile_dir=str(profile)
                )
                result["reason"] = mapped
                result["detail"] = result.get("detail") or f"escalate_ceiling:{kind}"
                final_result = result
            break

        print(
            f"==> antibot escalate attempt={attempt_i} kind={kind} "
            f"{bb_flags} -> {nxt}",
            flush=True,
            file=__import__("sys").stderr,
        )
        bb_flags = nxt
        step_dir = STEP_DIR_ROOT / f"{safe_host(host)}_ab{attempt_i + 1}"
        step_dir.mkdir(parents=True, exist_ok=True)

    assert final_result is not None
    final_result["antibot_log"] = antibot_log
    return final_result



def _run_signup_once(args: argparse.Namespace) -> dict[str, Any]:
    headed = not args.headless
    result = asyncio.run(
        sign_up(
            args.url,
            timeout_s=args.timeout,
            headed=headed,
            max_steps=args.max_steps,
            cdp_port=args.cdp_port,
        )
    )
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Sign up for a product and capture the session")
    ap.add_argument("--url", required=True, help="Product URL to sign up on")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--headed", action="store_true", default=True)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--cdp-port", type=int, default=None)
    args = ap.parse_args()

    # Inner worker: single attempt (supervisor sets MVP_SIGNUP_ANTIBOT_MAX_ATTEMPTS=1).
    if os.environ.get("MVP_ANTIBOT_INNER") == "1":
        result = _run_signup_once(args)
        esc_path = os.environ.get("MVP_ANTIBOT_ESCALATE_PATH")
        if result.get("reason") == "antibot_escalate" and esc_path:
            Path(esc_path).write_text(
                json.dumps(
                    {
                        "escalate_kind": result.get("escalate_kind"),
                        "bb_flags": result.get("browserbase_flags"),
                    }
                )
            )
            safe = {k: v for k, v in result.items() if k != "password"}
            print(json.dumps(safe, indent=2))
            raise SystemExit(78)
        safe = {k: v for k, v in result.items() if k != "password"}
        print(json.dumps(safe, indent=2))
        raise SystemExit(0 if result.get("ok") else 1)

    # Supervisor: restart worker on escalate (exit 78), including hard-unwedge exits.
    max_ab = max(1, int(os.environ.get("MVP_SIGNUP_ANTIBOT_MAX_ATTEMPTS", "4")))
    flags: dict[str, bool] | None = None
    last_code = 1
    for attempt in range(max_ab):
        esc = Path(os.environ.get("TMPDIR", "/tmp")) / f"antibot_esc_{os.getpid()}.json"
        if esc.exists():
            esc.unlink()
        env = os.environ.copy()
        env["MVP_ANTIBOT_INNER"] = "1"
        env["MVP_ANTIBOT_ESCALATE_PATH"] = str(esc)
        env["MVP_SIGNUP_ANTIBOT_MAX_ATTEMPTS"] = "1"
        if flags is not None:
            env["MVP_BB_FLAGS_JSON"] = json.dumps(flags)
        print(
            f"==> antibot supervisor attempt={attempt} flags={flags or 'cheap'}",
            flush=True,
        )
        proc = subprocess.run(
            [sys.executable, "-u", "-m", "mvp.auto_signup", *sys.argv[1:]],
            env=env,
            check=False,
        )
        last_code = int(proc.returncode or 0)
        if last_code == 78 and esc.exists():
            data = json.loads(esc.read_text())
            kind = data.get("escalate_kind") or "captcha"
            cur = data.get("bb_flags") or _cheap_bb_flags()
            nxt = _next_antibot_flags(cur, kind)
            if not nxt:
                print(
                    f"==> antibot supervisor ceiling kind={kind} flags={cur}",
                    flush=True,
                )
                raise SystemExit(1)
            flags = nxt
            print(
                f"==> antibot supervisor escalate kind={kind} -> {flags}",
                flush=True,
            )
            continue
        raise SystemExit(last_code)
    raise SystemExit(last_code)


if __name__ == "__main__":
    main()
