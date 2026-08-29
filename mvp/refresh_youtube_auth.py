"""Refresh YouTube/Gmail auth for MVP agents.

Opens a headed Chrome window on a dedicated profile and waits until you are
signed into YouTube (avatar / LOGIN_INFO). Cookie dumps from other browsers
or browser_cookie3 do NOT authenticate YouTube — this interactive capture does.

Usage:
  PYTHONPATH=src .venv/bin/python -m mvp.refresh_youtube_auth
  PYTHONPATH=src .venv/bin/python -m mvp.refresh_youtube_auth --timeout 1800
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / "secrets"
OUT = SECRETS / "youtube_storage_state.json"
PROFILE = SECRETS / "youtube_browser_profile"
CHECK_PNG = SECRETS / "youtube_auth_check.png"
CDP_PORT = int(os.environ.get("MVP_YT_AUTH_CDP_PORT", "9222"))
CHROME = os.environ.get(
    "MVP_CHROME_PATH",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


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


def _launch_chrome() -> subprocess.Popen:
    PROFILE.mkdir(parents=True, exist_ok=True)
    _kill_port(CDP_PORT)
    cmd = [
        CHROME,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={PROFILE.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "https://www.youtube.com/",
    ]
    log = open("/tmp/yt_chrome_auth.log", "ab")
    return subprocess.Popen(cmd, stdout=log, stderr=log, start_new_session=True)


async def _wait_signed_in(timeout_s: float) -> dict:
    from playwright.async_api import async_playwright

    deadline = time.time() + timeout_s
    last_msg = 0.0
    async with async_playwright() as p:
        browser = None
        while time.time() < deadline and browser is None:
            try:
                browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            except Exception:
                await asyncio.sleep(1)
        if browser is None:
            raise RuntimeError(f"Could not connect to Chrome CDP on port {CDP_PORT}")

        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        if "youtube.com" not in (page.url or ""):
            await page.goto("https://www.youtube.com/", wait_until="domcontentloaded")

        print(
            "\n=== ACTION REQUIRED ===\n"
            "A Chrome window is open on YouTube.\n"
            "1) Click Sign in\n"
            "2) Sign in with Gmail\n"
            "3) Stay on youtube.com until your avatar appears\n"
            f"Waiting up to {int(timeout_s)}s — I will keep polling until signed in.\n",
            flush=True,
        )

        while time.time() < deadline:
            try:
                if "youtube.com" not in (page.url or ""):
                    # User may be on accounts.google.com — fine.
                    pass
                avatar = await page.locator("#avatar-btn, button#avatar-btn").count()
                cookies = await ctx.cookies()
                has_login = any(c.get("name") == "LOGIN_INFO" for c in cookies)
                rich = 0
                if "youtube.com" in (page.url or ""):
                    rich = await page.locator("ytd-rich-item-renderer").count()
                now = time.time()
                if now - last_msg > 15:
                    print(
                        f"  … still waiting  avatar={avatar} LOGIN_INFO={has_login} "
                        f"rich_items={rich} url={page.url[:80]}",
                        flush=True,
                    )
                    last_msg = now
                # Require LOGIN_INFO + (avatar or home tiles). Avatar alone can flicker.
                if has_login and (avatar > 0 or rich >= 3):
                    # Give the feed a moment to settle, then capture.
                    if "youtube.com" not in (page.url or ""):
                        await page.goto(
                            "https://www.youtube.com/", wait_until="domcontentloaded"
                        )
                    await page.wait_for_timeout(4000)
                    rich = await page.locator("ytd-rich-item-renderer").count()
                    avatar = await page.locator("#avatar-btn, button#avatar-btn").count()
                    state = await ctx.storage_state()
                    OUT.parent.mkdir(parents=True, exist_ok=True)
                    OUT.write_text(json.dumps(state, indent=2))
                    await page.screenshot(path=str(CHECK_PNG))
                    from mvp.auth_state import mark_youtube_auth_ok

                    mark_youtube_auth_ok(True)
                    print(
                        f"Signed in. cookies={len(state.get('cookies') or [])} "
                        f"avatar={avatar} rich_items={rich} saved={OUT}",
                        flush=True,
                    )
                    return {
                        "ok": True,
                        "avatar": avatar,
                        "rich": rich,
                        "cookies": len(state.get("cookies") or []),
                    }
            except Exception as e:
                if time.time() - last_msg > 15:
                    print(f"  … poll error: {e}", flush=True)
                    last_msg = time.time()
            await asyncio.sleep(2)

        # Timed out — still save whatever we have for debugging.
        try:
            state = await ctx.storage_state()
            OUT.write_text(json.dumps(state, indent=2))
            await page.screenshot(path=str(CHECK_PNG))
        except Exception:
            pass
        return {"ok": False}


async def _verify_with_saved_state() -> bool:
    """Confirm storage_state alone can open a signed-in home feed."""
    from playwright.async_api import async_playwright

    if not OUT.is_file():
        return False
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True)
        ctx = await browser.new_context(
            storage_state=str(OUT),
            viewport={"width": 1280, "height": 900},
        )
        page = await ctx.new_page()
        await page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(6000)
        rich = await page.locator("ytd-rich-item-renderer").count()
        avatar = await page.locator("#avatar-btn, button#avatar-btn").count()
        await page.screenshot(path=str(CHECK_PNG))
        await browser.close()
        print(f"Verify storage_state: avatar={avatar} rich_items={rich}", flush=True)
        return avatar > 0 and rich >= 3


async def _verify_with_profile() -> bool:
    """Confirm the dedicated Chrome profile stays signed in."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE.resolve()),
            channel="chrome",
            headless=True,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(6000)
        rich = await page.locator("ytd-rich-item-renderer").count()
        avatar = await page.locator("#avatar-btn, button#avatar-btn").count()
        state = await ctx.storage_state()
        OUT.write_text(json.dumps(state, indent=2))
        await page.screenshot(path=str(CHECK_PNG))
        await ctx.close()
        print(f"Verify profile: avatar={avatar} rich_items={rich}", flush=True)
        return avatar > 0 and rich >= 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=float(os.environ.get("MVP_YT_AUTH_TIMEOUT", "1800")))
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    if args.verify_only:
        ok = asyncio.run(_verify_with_profile()) or asyncio.run(_verify_with_saved_state())
        return 0 if ok else 1

    proc = _launch_chrome()
    print(f"Launched Chrome pid={proc.pid} profile={PROFILE}", flush=True)
    try:
        result = asyncio.run(_wait_signed_in(args.timeout))
    finally:
        # Leave Chrome open if signed in so profile flushes; kill on failure.
        pass

    if not result.get("ok"):
        print(
            "Timed out without a signed-in YouTube session. "
            "Re-run and complete Gmail sign-in in the Chrome window.",
            flush=True,
        )
        return 1

    # Close the auth Chrome so the profile unlocks for verify / agents.
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    _kill_port(CDP_PORT)
    time.sleep(1)

    ok = asyncio.run(_verify_with_profile())
    if not ok:
        ok = asyncio.run(_verify_with_saved_state())
    if not ok:
        print("Signed-in capture saved, but verification did not see home tiles yet.", flush=True)
        return 1
    from mvp.auth_state import mark_youtube_auth_ok

    mark_youtube_auth_ok(True)
    print("YouTube signed-in auth ready for agents.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
