"""Autonomous sign-in for agent browser sessions.

Drives a real Chrome window through a Google (or generic) login using the
vault in ``secrets/credentials.json``, resolving challenges in this order:

  1. passkey / security-key prompts  -> escape to the password we hold
  2. password
  3. TOTP from ``totp_secret``       -> fully autonomous, no phone needed
  4. emailed code via IMAP           -> needs ``app_password``
  5. SMS code read from Messages     -> needs Text Message Forwarding
  6. "tap Yes on your phone"         -> pushes the phone and waits for the tap

Anything below TOTP costs a human, so keep ``totp_secret`` populated. On
success the Playwright storage_state is saved per host under
``secrets/site_states/`` so headless agents reuse the session. Secrets are
never logged; only which step is being handled.

Usage:
  PYTHONPATH=src .venv/bin/python -m mvp.auto_signin
  PYTHONPATH=src .venv/bin/python -m mvp.auto_signin --url https://www.youtube.com/ --headed
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mvp.credentials import credentials_for_url, totp_code, vault_status
from mvp.email_codes import wait_for_email_code
from mvp.notify import push
from mvp.sms_codes import messages_readable, wait_for_code

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "secrets"
PROFILE = Path(os.environ.get("MVP_SIGNIN_PROFILE") or SECRETS / "youtube_browser_profile")
STATE = SECRETS / "youtube_storage_state.json"
STATE_SIGNED = SECRETS / "youtube_storage_state.json.signed"
STEP_DIR = SECRETS / "signin_steps"
SITE_STATES = SECRETS / "site_states"
CDP_PORT = int(os.environ.get("MVP_YT_AUTH_CDP_PORT", "9222"))

MAX_ROUNDS = 40

GOOGLE_START = (
    "https://accounts.google.com/signin/v2/identifier"
    "?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2F"
)


def _is_google(host: str) -> bool:
    return "youtube.com" in host or "google." in host or "gmail.com" in host


def site_state_path(host: str) -> Path:
    safe = re.sub(r"[^a-z0-9.-]+", "_", host.lower())
    return SITE_STATES / f"{safe}.json"


def _find_chrome() -> str:
    override = os.environ.get("MVP_CHROME_PATH")
    if override:
        return override
    for path in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/local/bin/google-chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
    ):
        if Path(path).exists():
            return path
    raise RuntimeError("Chrome not found; set MVP_CHROME_PATH")


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


def _launch_chrome(start_url: str, *, headed: bool = True) -> subprocess.Popen:
    PROFILE.mkdir(parents=True, exist_ok=True)
    _kill_port(CDP_PORT)
    cmd = [
        _find_chrome(),
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={PROFILE.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--window-size=1440,900",
        start_url,
    ]
    if not headed:
        cmd.insert(1, "--headless=new")
    log = open("/tmp/auto_signin_chrome.log", "ab")
    return subprocess.Popen(cmd, stdout=log, stderr=log, start_new_session=True)


async def _visible(page: Any, selector: str) -> bool:
    try:
        loc = page.locator(selector).first
        return await loc.count() > 0 and await loc.is_visible()
    except Exception:
        return False


async def _click_text(page: Any, *texts: str) -> bool:
    """Click the first visible button/link matching any of these labels."""
    for text in texts:
        for selector in (
            f'button:has-text("{text}")',
            f'div[role="button"]:has-text("{text}")',
            f'a:has-text("{text}")',
            f'li:has-text("{text}")',
            f'*[role="link"]:has-text("{text}")',
        ):
            try:
                loc = page.locator(selector).first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=5000)
                    return True
            except Exception:
                continue
    return False


async def _shot(page: Any, label: str) -> None:
    STEP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(STEP_DIR / f"{label}.png"))
    except Exception:
        pass


async def _auth_form_present(page: Any) -> bool:
    """Any visible credential field, i.e. we are still being asked to log in."""
    for selector in (
        'input[type="password"]',
        'input[type="email"]',
        'input[name="identifier"]',
        'input[name="username"]',
    ):
        if await _visible(page, selector):
            return True
    return False


async def _trust_device(page: Any) -> None:
    """Tick "Don't ask again on this device" so 2FA is a one-time cost."""
    for selector in (
        'input[type="checkbox"][name="dontAskAgain"]',
        'input[type="checkbox"]',
    ):
        try:
            box = page.locator(selector).first
            if await box.count() and await box.is_visible() and not await box.is_checked():
                await box.check(timeout=3000)
                return
        except Exception:
            continue


async def _is_signed_in(ctx: Any, page: Any) -> tuple[bool, int, int]:
    cookies = await ctx.cookies()
    has_login = any(c.get("name") == "LOGIN_INFO" for c in cookies)
    avatar = 0
    rich = 0
    if "youtube.com" in (page.url or ""):
        avatar = await page.locator("#avatar-btn, button#avatar-btn").count()
        rich = await page.locator("ytd-rich-item-renderer").count()
    return (has_login and (avatar > 0 or rich >= 3)), avatar, rich


async def _handle_google_round(
    page: Any,
    creds: dict[str, Any],
    state: dict[str, Any],
) -> str:
    """Advance the Google login by one step. Returns a short action label."""
    body = ""
    try:
        body = (await page.inner_text("body")).lower()
    except Exception:
        pass

    # --- account chooser: pick the vault account instead of retyping it ---
    if "choose an account" in body or "accountchooser" in (page.url or "").lower():
        email = creds["username"]
        for selector in (
            f'div[data-identifier="{email}"]',
            f'li:has-text("{email}")',
            f'div[role="link"]:has-text("{email}")',
        ):
            try:
                loc = page.locator(selector).first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=5000)
                    return "chose_account"
            except Exception:
                continue
        try:
            await page.get_by_text(email, exact=False).first.click(timeout=5000)
            return "chose_account"
        except Exception:
            pass
        if await _click_text(page, "Use another account"):
            return "use_another_account"

    # --- email / identifier ---
    # A fresh profile renders this as input[name=identifier][type=text]; only
    # returning profiles get type=email. Both shapes must be handled.
    for email_selector in (
        'input[type="email"]',
        'input[name="identifier"]',
        'input[name="username"]',
    ):
        if not await _visible(page, email_selector):
            continue
        if state.get("email_filled") and "wrong" not in body:
            # Already submitted once; give the page a beat rather than looping.
            await page.wait_for_timeout(1500)
            return "wait_after_email"
        await page.fill(email_selector, creds["username"])
        state["email_filled"] = True
        if not await _click_text(page, "Next"):
            await page.keyboard.press("Enter")
        return "filled_email"

    # --- password ---
    if await _visible(page, 'input[type="password"]'):
        if state.get("password_filled") and "wrong password" not in body:
            await page.wait_for_timeout(1500)
            return "wait_after_password"
        await page.fill('input[type="password"]', creds["password"])
        state["password_filled"] = True
        if not await _click_text(page, "Next"):
            await page.keyboard.press("Enter")
        return "filled_password"

    # --- TOTP (authenticator app) ---
    if await _visible(page, 'input[name="totpPin"]'):
        code = totp_code(creds.get("totp_secret"))
        if not code and os.environ.get("MVP_ALLOW_CODE_DROP", "0").lower() in {
            "1",
            "true",
            "yes",
        }:
            code = await asyncio.to_thread(
                wait_for_code,
                timeout_s=float(os.environ.get("MVP_TOTP_WAIT_S", "120")),
                newer_than=0,
            )
        if not code:
            return "need_totp_secret"
        await page.fill('input[name="totpPin"]', code)
        await _trust_device(page)
        if not await _click_text(page, "Next", "Verify"):
            await page.keyboard.press("Enter")
        return "filled_totp"

    # --- SMS / voice code ---
    for sms_selector in ('input[name="idvPin"]', 'input[id="idvPin"]'):
        if await _visible(page, sms_selector):
            requested_at = state.get("sms_requested_at") or time.time()
            push(
                "UserSim needs your Google code",
                "Paste the 6-digit code into secrets/2fa_code.txt (or reply with it).",
            )
            code = await asyncio.to_thread(
                wait_for_code,
                timeout_s=float(os.environ.get("MVP_SMS_WAIT_S", "600")),
                newer_than=requested_at,
            )
            if not code:
                return "sms_timeout"
            await page.fill(sms_selector, code)
            await _trust_device(page)
            if not await _click_text(page, "Next", "Verify"):
                await page.keyboard.press("Enter")
            await page.wait_for_timeout(2500)
            # Some variants want the wire format "G-123456".
            try:
                body_after = (await page.inner_text("body")).lower()
            except Exception:
                body_after = ""
            if "wrong code" in body_after or "incorrect" in body_after:
                # Some variants want the wire format "G-123456".
                await page.fill(sms_selector, f"G-{code}")
                if not await _click_text(page, "Next", "Verify"):
                    await page.keyboard.press("Enter")
                await page.wait_for_timeout(2500)
                try:
                    body_after = (await page.inner_text("body")).lower()
                except Exception:
                    body_after = ""
                if "wrong code" in body_after or "expired" in body_after:
                    # Stale code: ask Google for a new one and wait for that instead.
                    if await _click_text(page, "Resend it", "Resend", "Get a new code"):
                        state["sms_requested_at"] = time.time()
                        return "resent_sms"
            return "filled_sms"

    # --- code emailed to the account itself (needs IMAP app password) ---
    if "an email with a verification code" in body or "ipe/verify" in (page.url or ""):
        field = None
        for candidate in ('input[name="idvPin"]', 'input[type="tel"]', 'input[type="text"]'):
            if await _visible(page, candidate):
                field = candidate
                break
        if field:
            app_password = creds.get("app_password")
            if not app_password:
                push(
                    "UserSim needs a Gmail app password",
                    "Google emailed the code to your own inbox; add app_password to the vault so I can read it.",
                )
                return "need_app_password"
            requested_at = state.get("email_requested_at") or time.time()
            state["email_requested_at"] = requested_at
            code = await asyncio.to_thread(
                wait_for_email_code,
                creds["username"],
                app_password,
                timeout_s=240.0,
                newer_than=requested_at,
            )
            if not code:
                return "email_code_timeout"
            await page.fill(field, code)
            if not await _click_text(page, "Next", "Verify"):
                await page.keyboard.press("Enter")
            return "filled_email_code"

    # --- phone number confirmation ---
    if await _visible(page, 'input[type="tel"]') and creds.get("phone"):
        await page.fill('input[type="tel"]', str(creds["phone"]))
        if not await _click_text(page, "Next", "Send"):
            await page.keyboard.press("Enter")
        return "filled_phone"

    # --- challenge chooser: pick the most automatable option available ---
    # Must be handled before the phone-tap branch, whose wording also appears here.
    is_chooser = (
        "choose how you want to sign in" in body
        or "challenge/selection" in (page.url or "").lower()
    )
    if is_chooser:
        # Password is a factor we actually hold, so always take it when offered —
        # otherwise "Try another way" drops into phone-only account recovery.
        if not state.get("password_filled") and await _click_text(
            page, "Enter your password", "Use your password"
        ):
            return "chose_password"

        state["sms_requested_at"] = time.time()
        # MVP_2FA_PREFER=totp|sms|tap forces a method when Google offers several.
        prefer = (os.environ.get("MVP_2FA_PREFER") or "").strip().lower()

        async def _try_totp() -> bool:
            coordinator_drop = os.environ.get("MVP_ALLOW_CODE_DROP", "0").lower() in {
                "1",
                "true",
                "yes",
            }
            return bool(creds.get("totp_secret") or coordinator_drop) and await _click_text(
                page, "Get a verification code from the Google Authenticator", "Authenticator"
            )

        async def _try_sms() -> bool:
            # A cloud worker can receive the code through secrets/2fa_code.txt
            # from a trusted coordinator even though it cannot read Messages.
            readable, _ = messages_readable()
            coordinator_drop = os.environ.get("MVP_ALLOW_CODE_DROP", "0").lower() in {
                "1",
                "true",
                "yes",
            }
            if not (readable or coordinator_drop):
                return False
            # Avoid Google's separate "one-time security code" / TOTP row.
            for selector in (
                'li:has-text("2-Step Verification phone")',
                'div[role="link"]:has-text("2-Step Verification phone")',
                'div[role="button"]:has-text("2-Step Verification phone")',
            ):
                try:
                    loc = page.locator(selector).first
                    if await loc.count() and await loc.is_visible():
                        await loc.click(timeout=5000)
                        return True
                except Exception:
                    continue
            return await _click_text(page, "Text message", "Send a text")

        async def _try_tap() -> bool:
            return await _click_text(page, "Tap Yes on your", "Google prompt")

        order = [("totp", _try_totp), ("sms", _try_sms), ("tap", _try_tap)]
        if prefer:
            order.sort(key=lambda item: item[0] != prefer)
        for name, attempt in order:
            if await attempt():
                return f"chose_{name}"
        if await _click_text(page, "Try another way to sign in", "Try another way"):
            return "opened_chooser"

    # --- passkey / security key: escape to a factor we hold ---
    if any(
        hint in body for hint in ("passkey", "security key", "use your fingerprint", "touch id")
    ):
        if await _click_text(page, "Enter your password", "Use your password", "Use password"):
            return "left_passkey_for_password"
        if await _click_text(page, "Try another way"):
            return "left_passkey"

    # --- "Do you have your phone?" gate before Google sends the prompt ---
    if "do you have your phone" in body:
        if await _click_text(page, "Yes"):
            return "confirmed_have_phone"

    # --- "Check your phone" / device tap ---
    tap_prompt = any(
        hint in body
        for hint in (
            "check your phone",
            "tap yes",
            "open the google app",
            "open the gmail app",
            "2-step verification",
        )
    )
    challenge_input = any(
        [
            await _visible(page, 'input[type="email"]'),
            await _visible(page, 'input[type="password"]'),
            await _visible(page, 'input[type="tel"]'),
            await _visible(page, 'input[name="totpPin"]'),
            await _visible(page, 'input[name="idvPin"]'),
        ]
    )
    if tap_prompt and not challenge_input:
        preferred = (os.environ.get("MVP_2FA_PREFER") or "").strip().lower()
        if preferred and preferred != "tap" and not state.get("left_default_tap"):
            if await _click_text(page, "Try another way"):
                state["left_default_tap"] = True
                return "left_default_tap"
        if not state.get("pushed_tap"):
            push(
                "Approve UserSim sign-in",
                "Google is asking you to tap Yes on your phone to finish the YouTube sign-in.",
            )
            state["pushed_tap"] = True
        await page.wait_for_timeout(3000)
        return "await_phone_tap"

    # --- consent / continue screens ---
    if await _click_text(page, "Continue", "Not now", "Confirm", "I understand"):
        return "clicked_continue"

    # --- generic site with no visible form: go find the login entry point ---
    if "accounts.google.com" not in (page.url or "") and not await _auth_form_present(page):
        if await _click_text(
            page, "Sign in", "Log in", "Login", "Sign In", "Continue with email"
        ):
            return "opened_login"

    return "no_action"


async def sign_in(
    url: str = "https://www.youtube.com/",
    *,
    timeout_s: float = 900.0,
    headed: bool = True,
    attach: bool = False,
) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    creds = credentials_for_url(url)
    if not creds or not creds.get("username") or not creds.get("password"):
        return {
            "ok": False,
            "reason": "no_credentials",
            "vault": vault_status(),
        }

    host = (urlparse(url).hostname or "").lower()
    google = _is_google(host)
    start_url = GOOGLE_START if google else url
    proc = None
    if not attach:
        proc = _launch_chrome(start_url, headed=headed)
        print(f"Chrome pid={proc.pid} profile={PROFILE}", flush=True)

    async with async_playwright() as p:
        browser = None
        deadline = time.time() + timeout_s
        while browser is None and time.time() < deadline:
            try:
                browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            except Exception:
                await asyncio.sleep(1)
        if browser is None:
            return {"ok": False, "reason": "cdp_unreachable"}

        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        signed, avatar, rich = await _is_signed_in(ctx, page)
        if not signed and "accounts.google.com" not in (page.url or ""):
            await page.goto(start_url, wait_until="domcontentloaded")

        state: dict[str, Any] = {}
        actions: list[str] = []
        for round_no in range(1, MAX_ROUNDS + 1):
            if time.time() > deadline:
                break
            # Back on the target host means the identity provider let us through.
            landed = (
                "youtube.com" in (page.url or "")
                if google
                else host in (page.url or "") and not await _auth_form_present(page)
            )
            if landed:
                await page.wait_for_timeout(3000)
                signed, avatar, rich = await _is_signed_in(ctx, page)
                if signed or not google:
                    saved = await ctx.storage_state()
                    text = json.dumps(saved, indent=2)
                    if google:
                        STATE.write_text(text)
                        STATE_SIGNED.write_text(text)
                        # The persistent browser profile is the source of truth.
                        # Auxiliary health metadata must never turn a completed
                        # Google login into a reported authentication failure.
                        try:
                            from mvp.auth_state import mark_youtube_auth_ok

                            mark_youtube_auth_ok(True)
                        except Exception as exc:
                            print(
                                f"auth metadata warning={type(exc).__name__}",
                                flush=True,
                            )
                    SITE_STATES.mkdir(parents=True, exist_ok=True)
                    site_state_path(host).write_text(text)
                    await _shot(page, "final_signed_in")
                    print(
                        f"SIGNED IN cookies={len(saved.get('cookies') or [])} "
                        f"avatar={avatar} rich={rich}",
                        flush=True,
                    )
                    return {
                        "ok": True,
                        "host": host,
                        "avatar": avatar,
                        "rich": rich,
                        "cookies": len(saved.get("cookies") or []),
                        "state_path": str(site_state_path(host)),
                        "actions": actions,
                    }

            action = await _handle_google_round(page, creds, state)
            actions.append(action)
            await _shot(page, f"{round_no:02d}_{action}")
            print(f"  [{round_no:02d}] {action}  url={(page.url or '')[:80]}", flush=True)

            if action in {
                "need_totp_secret",
                "need_sms_manual",
                "sms_timeout",
                "need_app_password",
                "email_code_timeout",
            }:
                return {"ok": False, "reason": action, "actions": actions}
            if action == "no_action":
                # Nothing recognized: let the page settle, then re-inspect.
                await page.wait_for_timeout(3000)
                if actions[-3:] == ["no_action"] * 3:
                    await _shot(page, "stuck")
                    return {"ok": False, "reason": "stuck", "actions": actions}
            else:
                await page.wait_for_timeout(2500)

        await _shot(page, "timeout")
        return {"ok": False, "reason": "timeout", "actions": actions}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://www.youtube.com/")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--headed", action="store_true", default=True)
    ap.add_argument("--headless", dest="headed", action="store_false")
    ap.add_argument("--attach", action="store_true")
    args = ap.parse_args()

    result = asyncio.run(
        sign_in(
            args.url,
            timeout_s=args.timeout,
            headed=args.headed,
            attach=args.attach,
        )
    )
    print(json.dumps({k: v for k, v in result.items() if k != "vault"}, indent=2))
    if not result.get("ok") and result.get("vault"):
        print("vault:", json.dumps(result["vault"], indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
