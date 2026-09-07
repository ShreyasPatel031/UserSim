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
    "unknown",
)


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


def _create_signup_browserbase_session():
    """Create the best Browserbase session this account's plan allows.

    Ideal: residential proxies + captcha solve + advanced stealth. Free tier
    rejects proxies (402) and verified/advanced stealth (403), so walk down the
    ladder instead of failing the whole signup.
    """
    from capability.browserbase_client import create_session

    attempts = [
        {"proxies": True, "solve_captchas": True, "advanced_stealth": True},
        {"proxies": True, "solve_captchas": True, "advanced_stealth": False},
        {"proxies": False, "solve_captchas": True, "advanced_stealth": False},
        {"proxies": False, "solve_captchas": False, "advanced_stealth": False},
    ]
    last_exc: BaseException | None = None
    for kwargs in attempts:
        try:
            session = create_session(keep_alive=False, **kwargs)
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
    """Signup via Browserbase when enabled and not forced local.

    Local Chrome on a GCP seed shares a datacenter ASN and fails captchas that a
    residential Browserbase session often clears. Opt in with
    ``MVP_SIGNUP_BROWSERBASE=1`` (or ``USE_BROWSERBASE=1``); ``MVP_FORCE_LOCAL_BROWSER=1``
    always wins for debugging.
    """
    if os.environ.get("MVP_FORCE_LOCAL_BROWSER", "").lower() in {"1", "true", "yes"}:
        return False
    raw = (
        os.environ.get("MVP_SIGNUP_BROWSERBASE")
        or os.environ.get("USE_BROWSERBASE")
        or ""
    )
    return raw.strip().lower() in {"1", "true", "yes"}


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
    if not headed:
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
    "bitwarden.com": "https://vault.bitwarden.com/#/register",
    "buffer.com": "https://login.buffer.com/signup",
    "calendly.com": "https://calendly.com/signup",
    "canva.com": "https://www.canva.com/signup",
    "clickup.com": "https://app.clickup.com/signup",
    "coda.io": "https://coda.io/signup",
    "dropbox.com": "https://www.dropbox.com/register",
    "figma.com": "https://www.figma.com/signup",
    "github.com": "https://github.com/signup",
    "gitlab.com": "https://gitlab.com/users/sign_up",
    "linear.app": "https://linear.app/signup",
    "loom.com": "https://www.loom.com/signup",
    "medium.com": "https://medium.com/m/signin",
    "miro.com": "https://miro.com/signup/",
    "notion.so": "https://www.notion.so/signup",
    "reddit.com": "https://www.reddit.com/register/",
    "todoist.com": "https://todoist.com/auth/signup",
    "webflow.com": "https://webflow.com/signup",
    "zoom.us": "https://www.zoom.us/signup",
}


def signup_start_url(host: str) -> str:
    """Deep signup link for ``host``, else its https homepage."""
    key = (host or "").lower().removeprefix("www.")
    return SIGNUP_START.get(key, f"https://www.{key}" if key else "")


# Authenticated landing routes, tried when the agent finishes on a marketing
# page. Signing up for canva ends on canva.com, which looks logged out.
VERIFY_URLS: dict[str, list[str]] = {
    "canva.com": ["https://www.canva.com/projects"],
    "todoist.com": ["https://app.todoist.com/app/inbox"],
    "notion.so": ["https://www.notion.so/"],
    "clickup.com": ["https://app.clickup.com/"],
    "figma.com": ["https://www.figma.com/files"],
    "miro.com": ["https://miro.com/app/dashboard/"],
    "loom.com": ["https://www.loom.com/looms/videos"],
    "coda.io": ["https://coda.io/docs"],
    "dropbox.com": ["https://www.dropbox.com/home"],
    "airtable.com": ["https://airtable.com/workspaces"],
    "calendly.com": ["https://calendly.com/event_types/user/me"],
    "buffer.com": ["https://publish.buffer.com/"],
    "webflow.com": ["https://webflow.com/dashboard"],
    "zoom.us": ["https://zoom.us/profile"],
    "linear.app": ["https://linear.app/"],
    "github.com": ["https://github.com/"],
    "gitlab.com": ["https://gitlab.com/dashboard"],
    "reddit.com": ["https://www.reddit.com/"],
    "medium.com": ["https://medium.com/me/stories/public"],
    "bitwarden.com": ["https://vault.bitwarden.com/#/vault"],
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

    class ReportBlockedParams(BaseModel):
        reason: str = Field(
            description=(
                "One of: card_required, sso_only, invite_only, waitlist, "
                "captcha_unsolved, unknown"
            )
        )
        detail: str = Field(default="", description="Short human-readable explanation")

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
        "Call this after requesting email verification. Returns the code digits.",
        param_model=EmptyParams,
    )
    async def get_email_code(params: EmptyParams):
        newer = ctx.get("email_requested_at") or time.time()
        code = await asyncio.to_thread(
            wait_for_signup_code,
            identity.email,
            timeout_s=float(os.environ.get("MVP_SIGNUP_EMAIL_TIMEOUT_S", "240")),
            newer_than=newer,
        )
        if not code:
            return ActionResult(
                error="No verification code arrived in email within timeout",
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
        "Returns the URL — navigate to it with go_to_url.",
        param_model=EmptyParams,
    )
    async def get_email_link(params: EmptyParams):
        newer = ctx.get("email_requested_at") or time.time()
        link = await asyncio.to_thread(
            wait_for_signup_link,
            identity.email,
            host=host,
            timeout_s=float(os.environ.get("MVP_SIGNUP_EMAIL_TIMEOUT_S", "240")),
            newer_than=newer,
        )
        if not link:
            return ActionResult(
                error="No confirmation link arrived in email within timeout",
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
                timeout_s=float(os.environ.get("MVP_SIGNUP_SMS_TIMEOUT_S", "180")),
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
        "If this returns an error, call report_blocked(captcha_unsolved) immediately — do not wait/loop.",
        param_model=EmptyParams,
    )
    async def solve_captcha(params: EmptyParams, browser_session):  # noqa: ANN001 — injected special arg
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
                    "If it fails again, call report_blocked(captcha_unsolved)."
                ),
                include_in_memory=True,
            )
        ctx["blocker"] = "captcha_unsolved"
        return ActionResult(
            error=(
                f"CAPTCHA unsolved after {attempts} attempts ({result}). "
                "Call report_blocked with reason captcha_unsolved now — do not retry wait loops."
            ),
            include_in_memory=True,
        )

    @tools.registry.action(
        "Stop signup — the product requires something we cannot automate "
        "(card_required, sso_only, invite_only, waitlist, captcha_unsolved, unknown). "
        "Call this instead of looping when blocked.",
        param_model=ReportBlockedParams,
        terminates_sequence=True,
    )
    async def report_blocked(params: ReportBlockedParams):
        reason = (params.reason or "unknown").strip().lower()
        if reason not in BLOCK_REASONS:
            reason = "unknown"
        ctx["blocker"] = reason
        ctx["blocker_detail"] = params.detail or ""
        ctx["done"] = True
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
    """Create an account on ``url`` and persist the signed-in Chrome profile."""
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
    }

    if use_bb:
        from capability.browserbase_client import close_session

        # Best available session for this Browserbase plan (proxies may 402 on free).
        bb_session, bb_flags = await asyncio.to_thread(_create_signup_browserbase_session)
        cdp_url = bb_session.connect_url
        result["backend"] = "browserbase"
        result["browserbase_session_url"] = bb_session.session_url
        result["browserbase_flags"] = bb_flags
        print(
            f"Browserbase session={bb_session.id} url={bb_session.session_url} flags={bb_flags}",
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
        "identity": identity,
        "host": host,
        "page_getter": lambda: None,
        "blocker": None,
        "blocker_detail": None,
        "done": False,
        "sms_number": None,
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
            model = (os.environ.get("MVP_SIGNUP_MODEL") or MODEL or "gemini-2.5-flash").strip()
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
                captcha_solver=True if use_bb else (
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
                f"6. If a CAPTCHA/Cloudflare challenge blocks you: call solve_captcha() once. "
                f"If it fails, immediately call report_blocked(captcha_unsolved). Do not wait-loop.\n"
                f"7. Skip or dismiss onboarding tours once the account exists.\n"
                f"8. Stop when you are clearly signed in (account menu / dashboard / logout).\n"
                f"If the product requires a credit card, SSO-only, invite-only access, "
                f"or a waitlist, call report_blocked with the matching reason.\n"
                f"Do NOT try to pay. Prefer email signup; use Google/GitHub SSO only if email signup is absent."
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
                    "authenticated experience. Prefer the email/password path. Be decisive; "
                    "do not loop on the same form. Call report_blocked when stuck on a "
                    "hard gate (card, SSO-only, invite, waitlist)."
                ),
            )

            history = None
            try:
                history = await asyncio.wait_for(
                    agent.run(max_steps=max_steps),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                result["reason"] = "timeout"
            except Exception as exc:
                result["reason"] = f"agent_error:{type(exc).__name__}:{exc}"[:300]

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

            # Always snapshot cookies before judging — Browserbase sessions die in
            # ``finally``, so a false-negative signed-in heuristic used to throw away
            # a real account (Todoist completed signup then reported not_signed_in).
            state: dict[str, Any] | None = None
            try:
                state = await pw_ctx.storage_state()
                SITE_STATES.mkdir(parents=True, exist_ok=True)
                site_state_path(host).write_text(json.dumps(state, indent=2))
            except Exception as exc:
                result["state_error"] = str(exc)[:200]

            # Onboarding often ends on a "Getting ready…" splash that redirects a
            # few seconds later, so a single probe reports a fresh account as
            # not_signed_in. Re-probe for a short window before giving up.
            signed = False
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

            if ctx.get("blocker"):
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
                return result

            if signed:
                update_identity(
                    url,
                    status="signed_up",
                    blocker=None,
                    profile_dir=str(profile),
                )
                result.update({"ok": True, "reason": "signed_up"})
                return result

            result["reason"] = result.get("reason") or "not_signed_in"
            if history is not None:
                try:
                    result["steps"] = getattr(history, "number_of_steps", lambda: None)()
                except Exception:
                    pass
            update_identity(
                url,
                status="provisioned",
                blocker=result.get("reason"),
                profile_dir=str(profile),
            )
            return result
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Sign up for a product and capture the session")
    ap.add_argument("--url", required=True, help="Product URL to sign up on")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--headed", action="store_true", default=True)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--cdp-port", type=int, default=None)
    args = ap.parse_args()
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
    # Never print the password.
    safe = {k: v for k, v in result.items() if k != "password"}
    print(json.dumps(safe, indent=2))
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
