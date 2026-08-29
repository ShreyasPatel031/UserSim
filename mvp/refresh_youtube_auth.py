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
OUT_SIGNED = SECRETS / "youtube_storage_state.json.signed"
PROFILE = SECRETS / "youtube_browser_profile"
CHECK_PNG = SECRETS / "youtube_auth_check.png"
CDP_PORT = int(os.environ.get("MVP_YT_AUTH_CDP_PORT", "9222"))


def _find_chrome() -> str:
    override = os.environ.get("MVP_CHROME_PATH")
    if override:
        return override
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/local/bin/google-chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return candidates[0]


CHROME = _find_chrome()


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


def _save_state(state: dict) -> None:
    """Write canonical + immutable backup. Never lose a good capture."""
    text = json.dumps(state, indent=2)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    OUT_SIGNED.write_text(text)


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
                        f"rich_items={rich} url={(page.url or '')[:80]}",
                        flush=True,
                    )
                    last_msg = now
                if has_login and (avatar > 0 or rich >= 3):
                    if "youtube.com" not in (page.url or ""):
                        await page.goto(
                            "https://www.youtube.com/", wait_until="domcontentloaded"
                        )
                    await page.wait_for_timeout(4000)
                    rich = await page.locator("ytd-rich-item-renderer").count()
                    avatar = await page.locator("#avatar-btn, button#avatar-btn").count()
                    state = await ctx.storage_state()
                    _save_state(state)
                    await page.screenshot(path=str(CHECK_PNG))
                    print(
                        f"Signed in. cookies={len(state.get('cookies') or [])} "
                        f"avatar={avatar} rich_items={rich} saved={OUT} backup={OUT_SIGNED}",
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

        try:
            state = await ctx.storage_state()
            # Debug-only dump — do not overwrite a prior .signed backup.
            OUT.write_text(json.dumps(state, indent=2))
            await page.screenshot(path=str(CHECK_PNG))
        except Exception:
            pass
        return {"ok": False}


async def _verify_with_saved_state() -> bool:
    """Confirm storage_state can open a signed-in home feed (headed — headless drops Google auth)."""
    from playwright.async_api import async_playwright

    state_path = OUT_SIGNED if OUT_SIGNED.is_file() else OUT
    if not state_path.is_file():
        return False
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=False)
        ctx = await browser.new_context(
            storage_state=str(state_path),
            viewport={"width": 1280, "height": 900},
        )
        page = await ctx.new_page()
        await page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(6000)
        rich = await page.locator("ytd-rich-item-renderer").count()
        avatar = await page.locator("#avatar-btn, button#avatar-btn").count()
        await page.screenshot(path=str(CHECK_PNG))
        if avatar > 0 and rich >= 3:
            # Refresh canonical from known-good backup without risk of empty overwrite.
            data = state_path.read_text()
            OUT.write_text(data)
            OUT_SIGNED.write_text(data)
        await browser.close()
        print(f"Verify storage_state: avatar={avatar} rich_items={rich} from={state_path}", flush=True)
        return avatar > 0 and rich >= 3


async def _verify_with_profile() -> bool:
    """Confirm the dedicated Chrome profile stays signed in (headed)."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE.resolve()),
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(6000)
        rich = await page.locator("ytd-rich-item-renderer").count()
        avatar = await page.locator("#avatar-btn, button#avatar-btn").count()
        # Only rewrite OUT if still signed in — never clobber a good dump with empty cookies.
        if avatar > 0 and rich >= 3:
            state = await ctx.storage_state()
            _save_state(state)
        await page.screenshot(path=str(CHECK_PNG))
        await ctx.close()
        print(f"Verify profile: avatar={avatar} rich_items={rich}", flush=True)
        return avatar > 0 and rich >= 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("MVP_YT_AUTH_TIMEOUT", "1800")),
    )
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument(
        "--attach",
        action="store_true",
        help="Use a Chrome already listening on CDP_PORT instead of launching one.",
    )
    args = ap.parse_args()

    if args.verify_only:
        ok = asyncio.run(_verify_with_saved_state()) or asyncio.run(_verify_with_profile())
        if ok:
            from mvp.auth_state import mark_youtube_auth_ok

            mark_youtube_auth_ok(True)
        return 0 if ok else 1

    proc = None
    if args.attach:
        print(f"Attaching to Chrome already on CDP port {CDP_PORT}", flush=True)
    else:
        proc = _launch_chrome()
        print(f"Launched Chrome pid={proc.pid} profile={PROFILE}", flush=True)
    result = asyncio.run(_wait_signed_in(args.timeout))

    if not result.get("ok"):
        print(
            "Timed out without a signed-in YouTube session. "
            "Re-run and complete Gmail sign-in in the Chrome window.",
            flush=True,
        )
        return 1

    # Let Chrome flush cookies to the profile, then quit cleanly so the profile unlocks.
    time.sleep(2)
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        _kill_port(CDP_PORT)
        time.sleep(1.5)

    ok = asyncio.run(_verify_with_saved_state())
    if not ok and proc is not None:
        # Skip when attached: the live Chrome still holds a lock on the profile dir.
        ok = asyncio.run(_verify_with_profile())
    if not ok:
        print(
            f"Capture saved at {OUT_SIGNED}, but a fresh browser did not keep the session. Re-run auth.",
            flush=True,
        )
        return 1
    from mvp.auth_state import mark_youtube_auth_ok

    mark_youtube_auth_ok(True)
    print("YouTube signed-in auth ready for agents.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
