"""Auto-save dashboard sessions from the shared Chrome profile (no Enter prompts)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from capability import USER_AGENT, VIEWPORT
from capability.voice_ai_dashboards import (
    DASHBOARDS,
    DEFAULT_EMAIL,
    PROFILE_DIR,
    SESSION_DIR,
    session_path,
)

# macOS default Chrome — Google OAuth works here; Chrome must be fully quit before save.
DEFAULT_MAC_CHROME = Path.home() / "Library/Application Support/Google/Chrome"


def _classify(dash, url: str, body: str) -> str:
    low_url = url.lower()
    low_body = body.lower()
    if any(h in low_url for h in dash.logged_in_url_hints):
        return "logged_in"
    if any(h in low_body for h in dash.logged_in_body_hints):
        return "logged_in"
    if any(h in low_body for h in dash.login_body_hints):
        return "login"
    return "unknown"


async def _verify_page(page, dash) -> dict:
    await page.goto(dash.dashboard_url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(2000)
    body = (await page.inner_text("body"))[:8000]
    state = _classify(dash, page.url, body)
    return {
        "key": dash.key,
        "name": dash.name,
        "url": page.url,
        "state": state,
        "title": await page.title(),
    }


async def snapshot(
    keys: list[str] | None,
    headed: bool = False,
    wait_s: float = 0,
    chrome_user_data: Path | None = None,
) -> list[dict]:
    from playwright.async_api import async_playwright

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    user_data = chrome_user_data or PROFILE_DIR
    user_data.mkdir(parents=True, exist_ok=True)
    dashboards = [d for d in DASHBOARDS if not keys or d.key in keys]
    results = []

    launch_kw = {
        "user_data_dir": str(user_data),
        "headless": not headed,
        "viewport": VIEWPORT,
        "user_agent": USER_AGENT,
        "ignore_default_args": ["--enable-automation"],
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--profile-directory=Default",
        ],
    }
    async with async_playwright() as p:
        try:
            context = await p.chromium.launch_persistent_context(channel="chrome", **launch_kw)
        except Exception:
            context = await p.chromium.launch_persistent_context(**launch_kw)
        page = context.pages[0] if context.pages else await context.new_page()
        for dash in dashboards:
            if headed and wait_s > 0:
                await page.goto(dash.login_url, wait_until="domcontentloaded", timeout=60000)
                deadline = asyncio.get_event_loop().time() + wait_s
                while asyncio.get_event_loop().time() < deadline:
                    await page.wait_for_timeout(3000)
                    body = (await page.inner_text("body"))[:8000]
                    if _classify(dash, page.url, body) == "logged_in":
                        break
                    if "dashboard" in page.url.lower():
                        break
            check = await _verify_page(page, dash)
            url_low = (check.get("url") or "").lower()
            on_login = (
                check.get("state") == "login"
                or "/login" in url_low
                or "/u/login" in url_low
                or "auth." in url_low
            )
            if check.get("state") == "logged_in" or (not on_login and check.get("state") != "error"):
                await context.storage_state(path=str(session_path(dash.key)))
                check["saved"] = True
            else:
                check["saved"] = False
            results.append(check)
        await context.close()

    manifest = {
        "email": DEFAULT_EMAIL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
    (SESSION_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Comma-separated keys")
    ap.add_argument("--headed", action="store_true", help="Show Chrome (for one-time sign-in)")
    ap.add_argument("--wait", type=float, default=0, help="Seconds to wait on login (headed)")
    ap.add_argument(
        "--from-default-chrome",
        action="store_true",
        help="Read cookies from your normal Chrome profile (Chrome must be quit)",
    )
    args = ap.parse_args()
    keys = [x.strip() for x in args.only.split(",")] if args.only else None
    chrome_ud = DEFAULT_MAC_CHROME if args.from_default_chrome else None
    if args.from_default_chrome and not DEFAULT_MAC_CHROME.is_dir():
        print(f"Chrome profile not found: {DEFAULT_MAC_CHROME}", file=sys.stderr)
        return 1
    results = asyncio.run(snapshot(keys, headed=args.headed, wait_s=args.wait, chrome_user_data=chrome_ud))
    for r in results:
        mark = "saved" if r.get("saved") else r.get("state")
        print(f"{r['key']}: {mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
