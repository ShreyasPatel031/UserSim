"""Apple ID sign-in steps for appleid.apple.com / idmsa.apple.com.

Covers the Apple ID web login and "Sign in with Apple" (``/auth/authorize``).
Two-factor auth goes through the "text me" path so the code arrives as an SMS,
which the handset forwards to ntfy (see :mod:`mvp.sms_provider`). A push to a
trusted Apple device is unreadable from a VM, so it is always declined in
favour of the phone number.

Credentials come from a vault entry matching ``appleid.apple.com`` or, failing
that, ``APPLE_ID_EMAIL`` / ``APPLE_ID_PASSWORD``.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

APPLE_AUTH_HOSTS = ("appleid.apple.com", "idmsa.apple.com", "account.apple.com")

_EMAIL_SELECTORS = ("#account_name_text_field", 'input[type="email"]', 'input[name="accountName"]')
_PASSWORD_SELECTORS = ("#password_text_field", 'input[type="password"]')
_CODE_SELECTORS = (
    "input.form-security-code-input",
    'input[id^="char"]',
    'input[autocomplete="one-time-code"]',
)


def is_apple_auth_url(url: str | None) -> bool:
    return any(host in (url or "") for host in APPLE_AUTH_HOSTS)


def apple_credentials() -> dict[str, Any] | None:
    from mvp.credentials import credentials_for_url

    creds = credentials_for_url("https://appleid.apple.com/")
    if creds and creds.get("username") and creds.get("password"):
        return creds
    user = (os.environ.get("APPLE_ID_EMAIL") or "").strip()
    password = os.environ.get("APPLE_ID_PASSWORD") or ""
    if user and password:
        return {"match": list(APPLE_AUTH_HOSTS), "username": user, "password": password}
    return None


def _frames(page: Any) -> list[Any]:
    """Apple renders the login widget in an idmsa.apple.com iframe; check it first."""
    frames = [f for f in page.frames if is_apple_auth_url(f.url) and f is not page.main_frame]
    return frames + [page.main_frame]


async def _visible_in(frame: Any, selector: str) -> bool:
    try:
        loc = frame.locator(selector).first
        return bool(await loc.count()) and await loc.is_visible()
    except Exception:
        return False


async def _find(page: Any, selectors: tuple[str, ...]) -> tuple[Any, str] | None:
    for frame in _frames(page):
        for selector in selectors:
            if await _visible_in(frame, selector):
                return frame, selector
    return None


async def _click_text(page: Any, *texts: str) -> bool:
    for frame in _frames(page):
        for text in texts:
            for loc in (
                frame.get_by_role("button", name=text, exact=False),
                frame.get_by_role("link", name=text, exact=False),
                frame.get_by_text(text, exact=False),
            ):
                try:
                    target = loc.first
                    if await target.count() and await target.is_visible():
                        await target.click(timeout=5000)
                        return True
                except Exception:
                    continue
    return False


async def _body_text(page: Any) -> str:
    parts = []
    for frame in _frames(page):
        try:
            parts.append(await frame.inner_text("body"))
        except Exception:
            continue
    return "\n".join(parts).lower()


def _wait_sms_code(newer_than: float, timeout_s: float) -> str | None:
    from mvp.sms_provider import Number, _backend, vault_phone, wait_for_sms

    number = Number(phone=vault_phone() or "", backend=_backend())
    if number.backend not in {"messages", "ntfy"}:
        # A leased number cannot receive codes for the owner's Apple ID.
        number.backend = "ntfy"
    return wait_for_sms(number, timeout_s=timeout_s, newer_than=newer_than)


async def handle_apple_round(page: Any, creds: dict[str, Any], state: dict[str, Any]) -> str:
    """Advance an Apple ID login by one step. Returns a short action label."""
    body = await _body_text(page)

    code_field = await _find(page, _CODE_SELECTORS)
    if code_field:
        if not state.get("sms_requested_at"):
            # Default delivery is a trusted-device push; switch to SMS first.
            if await _click_text(
                page,
                "Didn't get a verification code",
                "Can't use this device",
                "Use phone number",
            ):
                state["asked_alternatives"] = True
                await page.wait_for_timeout(1500)
            if await _click_text(page, "Text code to", "Text Message", "Send code", "Text me"):
                state["sms_requested_at"] = time.time()
                return "requested_sms"
            if state.get("asked_alternatives"):
                # Apple sometimes texts the only trusted number without a picker.
                state["sms_requested_at"] = time.time()
            else:
                return "no_sms_option"
        code = await asyncio.to_thread(
            _wait_sms_code,
            state["sms_requested_at"],
            float(os.environ.get("MVP_SMS_WAIT_S", "600")),
        )
        if not code:
            return "sms_timeout"
        frame, selector = code_field
        await frame.locator(selector).first.click()
        await page.keyboard.type(code, delay=80)
        state["code_entered"] = True
        return "filled_sms"

    if "trust this browser" in body or "trust this computer" in body:
        if await _click_text(page, "Trust"):
            return "trusted_browser"

    # Sign in with Apple consent: share the real address so the product's own
    # email verification (if any) reaches the agent's inbox.
    if "share my email" in body and await _click_text(page, "Share My Email"):
        state["shared_email"] = True
        return "chose_share_email"
    if ("continue" in body or "use apple id" in body) and state.get("password_filled"):
        if await _click_text(page, "Continue", "Use Apple ID"):
            return "consented"

    password_field = await _find(page, _PASSWORD_SELECTORS)
    if password_field:
        if state.get("password_filled") and "incorrect" not in body:
            await page.wait_for_timeout(1500)
            return "wait_after_password"
        frame, selector = password_field
        await frame.locator(selector).first.fill(creds["password"])
        state["password_filled"] = True
        if not await _click_text(page, "Sign In", "Continue"):
            await page.keyboard.press("Enter")
        return "filled_password"

    email_field = await _find(page, _EMAIL_SELECTORS)
    if email_field:
        if state.get("email_filled"):
            await page.wait_for_timeout(1500)
            return "wait_after_email"
        frame, selector = email_field
        await frame.locator(selector).first.fill(creds["username"])
        state["email_filled"] = True
        if not await _click_text(page, "Continue", "Next"):
            await page.keyboard.press("Enter")
        return "filled_email"

    return "no_action"
