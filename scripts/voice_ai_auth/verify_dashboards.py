#!/usr/bin/env python3
"""Headless verify of saved voice-AI dashboard sessions."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from capability import USER_AGENT, VIEWPORT
from capability.voice_ai_dashboards import DASHBOARDS, SESSION_DIR, session_path


async def verify(keys: list[str] | None) -> list[dict]:
    from playwright.async_api import async_playwright

    dashboards = [d for d in DASHBOARDS if not keys or d.key in keys]
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for dash in dashboards:
            sp = session_path(dash.key)
            if not sp.is_file():
                results.append({"key": dash.key, "state": "no_session"})
                continue
            context = await browser.new_context(
                viewport=VIEWPORT,
                user_agent=USER_AGENT,
                storage_state=str(sp),
            )
            page = await context.new_page()
            try:
                await page.goto(dash.dashboard_url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(2000)
                body = (await page.inner_text("body"))[:6000].lower()
                url_low = page.url.lower()
                logged = any(h in body for h in dash.logged_in_body_hints)
                login = any(h in body for h in dash.login_body_hints)
                on_login_url = "/login" in url_low or "/u/login" in url_low or "auth." in url_low
                if any(h in url_low for h in dash.logged_in_url_hints):
                    logged = True
                if on_login_url:
                    state = "login"
                elif logged and not login:
                    state = "logged_in"
                elif login:
                    state = "login"
                elif not on_login_url and "dashboard." in url_low:
                    state = "logged_in"
                else:
                    state = "unknown"
                results.append(
                    {
                        "key": dash.key,
                        "state": state,
                        "url": page.url,
                        "title": await page.title(),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                results.append({"key": dash.key, "state": "error", "error": str(exc)[:200]})
            await context.close()
        await browser.close()
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Comma-separated keys")
    args = ap.parse_args()
    keys = [x.strip() for x in args.only.split(",")] if args.only else None
    results = asyncio.run(verify(keys))
    out = SESSION_DIR / "verify_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    for r in results:
        mark = "OK" if r.get("state") == "logged_in" else r.get("state")
        print(f"{r['key']}: {mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
