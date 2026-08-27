#!/usr/bin/env python3
"""Interactive login to voice-AI dashboards; saves Playwright storage state per platform.

Uses one persistent Chrome profile so Google SSO can be reused across products.

Usage:
  PYTHONPATH=src python3 scripts/voice_ai_auth/login_dashboards.py
  PYTHONPATH=src python3 scripts/voice_ai_auth/login_dashboards.py --only bland,vapi
  PYTHONPATH=src python3 scripts/voice_ai_auth/login_dashboards.py --verify-only

Sign in with Google using shreyashfs@gmail.com when prompted.
After each site loads the dashboard, press Enter in this terminal to save session.
"""

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
    DASHBOARD_BY_KEY,
    DEFAULT_EMAIL,
    PROFILE_DIR,
    SESSION_DIR,
    session_path,
)


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


async def verify_one(page, dash) -> dict:
    try:
        await page.goto(dash.dashboard_url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2500)
        body = (await page.inner_text("body"))[:8000]
        state = _classify(dash, page.url, body)
        return {
            "key": dash.key,
            "name": dash.name,
            "url": page.url,
            "state": state,
            "title": await page.title(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"key": dash.key, "name": dash.name, "state": "error", "error": str(exc)[:300]}


async def login_flow(only: list[str] | None, verify_only: bool) -> int:
    from playwright.async_api import async_playwright

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    dashboards = [d for d in DASHBOARDS if not only or d.key in only]
    if only and len(dashboards) != len(only):
        missing = set(only) - {d.key for d in dashboards}
        print(f"Unknown keys: {missing}", file=sys.stderr)
        return 1

    async with async_playwright() as p:
        launch_kw = {
            "user_data_dir": str(PROFILE_DIR),
            "headless": False,
            "viewport": VIEWPORT,
            "user_agent": USER_AGENT,
            "ignore_default_args": ["--enable-automation"],
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        }
        try:
            context = await p.chromium.launch_persistent_context(channel="chrome", **launch_kw)
        except Exception:
            context = await p.chromium.launch_persistent_context(**launch_kw)

        page = context.pages[0] if context.pages else await context.new_page()

        print(f"Use Google account: {DEFAULT_EMAIL}")
        print("For each product: Sign in with Google → complete CAPTCHA if needed → wait for dashboard.")
        print()

        if verify_only:
            results = [await verify_one(page, d) for d in dashboards]
            context.close()
            _print_results(results)
            return 0

        results = []
        for dash in dashboards:
            print(f"\n{'='*60}")
            print(f"  {dash.name} ({dash.key})")
            print(f"  Login: {dash.login_url}")
            print(f"  Target: {dash.dashboard_url}")
            print(f"{'='*60}")
            await page.goto(dash.login_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1500)
            input(f"  When {dash.name} dashboard is loaded, press Enter to save session… ")

            check = await verify_one(page, dash)
            results.append(check)
            await context.storage_state(path=str(session_path(dash.key)))
            print(f"  Saved → {session_path(dash.key)}  state={check.get('state')}")

        manifest = {
            "email": DEFAULT_EMAIL,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "profile_dir": str(PROFILE_DIR),
            "results": results,
        }
        manifest_path = SESSION_DIR / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"\nManifest: {manifest_path}")
        _print_results(results)
        context.close()
    return 0


def _print_results(results: list[dict]) -> None:
    print("\nStatus:")
    for r in results:
        mark = "✓" if r.get("state") == "logged_in" else "✗"
        print(f"  {mark} {r.get('name', r.get('key'))}: {r.get('state')} {r.get('url', '')}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Login to voice-AI dashboards")
    ap.add_argument("--only", help="Comma-separated keys (bland,vapi,retell,...)")
    ap.add_argument("--verify-only", action="store_true", help="Check sessions without login UI")
    args = ap.parse_args()
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    return asyncio.run(login_flow(only, args.verify_only))


if __name__ == "__main__":
    raise SystemExit(main())
