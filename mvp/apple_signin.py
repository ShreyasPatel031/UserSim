"""Autonomous Apple Account sign-in with SMS two-factor.

Apple's sign-in form lives in an ``idmsa.apple.com`` iframe. After the password
it sends a code to the owner's trusted devices; we instead pick
"Can't get to your devices?" -> "Text code to ...", and read the SMS the
owner's phone forwards to the ntfy topic (``MVP_SMS_BACKEND=ntfy``). The
browser is then trusted and its storage state saved to
``secrets/site_states/apple.com.json`` for reuse by "Sign in with Apple".

Credentials come from the vault entry matching ``apple.com``.

    python -m mvp.apple_signin [--headed]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from mvp.credentials import credentials_for_url
from mvp.sms_provider import Number, wait_for_sms

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "secrets" / "site_states" / "apple.com.json"
SHOTS = ROOT / "secrets" / "apple_signin_shots"
START_URL = "https://account.apple.com/sign-in"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _auth_frame(page: Any) -> Any | None:
    return next((f for f in page.frames if "idmsa.apple.com" in f.url), None)


async def _click_first(frame: Any, *texts: str) -> str | None:
    for text in texts:
        try:
            loc = frame.get_by_text(text)
            if await loc.count():
                await loc.first.click(timeout=5000)
                return text
        except Exception:
            continue
    return None


async def _signed_in(page: Any) -> bool:
    if _auth_frame(page) is not None:
        return False
    if "/account/manage" in (page.url or ""):
        return True
    try:
        return await page.get_by_text("Sign Out", exact=True).count() > 0
    except Exception:
        return False


async def sign_in(*, headed: bool = False, sms_wait_s: float = 300.0) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    creds = credentials_for_url(START_URL)
    if not creds or not creds.get("username") or not creds.get("password"):
        return {"ok": False, "reason": "no_credentials"}

    SHOTS.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        launch: dict[str, Any] = {"headless": not headed, "args": ["--no-sandbox"]}
        exe = os.environ.get("MVP_CHROMIUM_PATH") or "/opt/pw-browsers/chromium"
        if Path(exe).exists():
            launch["executable_path"] = exe
        browser = await p.chromium.launch(**launch)
        ctx_kwargs: dict[str, Any] = {"user_agent": UA}
        if STATE_PATH.is_file():
            ctx_kwargs["storage_state"] = str(STATE_PATH)
        ctx = await browser.new_context(**ctx_kwargs)
        page = await ctx.new_page()
        try:
            await page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(6000)
            steps: list[str] = []

            if not await _signed_in(page):
                frame = _auth_frame(page)
                if frame is None:
                    return {"ok": False, "reason": "no_auth_frame"}
                await frame.fill("#account_name_text_field", creds["username"])
                await frame.click("#sign-in")
                await page.wait_for_timeout(3000)
                await _click_first(frame, "Continue with Password")
                await frame.fill("#password_text_field", creds["password"])
                await frame.click("#sign-in")
                steps.append("password")
                await page.wait_for_timeout(6000)

                frame = _auth_frame(page)
                body = (await frame.inner_text("body")).lower() if frame else ""
                if "incorrect" in body or "check the account information" in body:
                    return {"ok": False, "reason": "bad_password", "steps": steps}

                if frame and "verification code" in body:
                    await _click_first(frame, "Can’t get to your devices?", "Can't get to your devices?")
                    await page.wait_for_timeout(2000)
                    requested_at = time.time()
                    if not await _click_first(frame, "Text code to"):
                        await page.screenshot(path=str(SHOTS / "no_sms_option.png"))
                        return {"ok": False, "reason": "no_sms_option", "steps": steps}
                    steps.append("sms_requested")
                    code = await asyncio.to_thread(
                        wait_for_sms,
                        Number(phone="", backend="ntfy"),
                        timeout_s=sms_wait_s,
                        newer_than=requested_at,
                    )
                    if not code:
                        return {"ok": False, "reason": "sms_timeout", "steps": steps}
                    await frame.locator("input[type=tel]").first.click()
                    await page.keyboard.type(code, delay=120)
                    steps.append("sms_entered")
                    await page.wait_for_timeout(5000)

                # "Trust this browser?" — keeps the next run free of 2FA.
                frame = _auth_frame(page)
                if frame is not None:
                    try:
                        trust = frame.get_by_role("button", name="Trust")
                        if await trust.count():
                            await trust.first.click(timeout=5000)
                            steps.append("trusted")
                    except Exception:
                        pass
                    await page.wait_for_timeout(6000)

            await page.screenshot(path=str(SHOTS / "final.png"))
            if not await _signed_in(page):
                return {"ok": False, "reason": "not_signed_in", "steps": steps, "url": page.url}

            state = await ctx.storage_state()
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(state))
            return {
                "ok": True,
                "steps": steps,
                "cookies": len(state.get("cookies") or []),
                "state_path": str(STATE_PATH),
            }
        finally:
            await browser.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--sms-wait", type=float, default=300.0)
    args = ap.parse_args()
    result = asyncio.run(sign_in(headed=args.headed, sms_wait_s=args.sms_wait))
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
