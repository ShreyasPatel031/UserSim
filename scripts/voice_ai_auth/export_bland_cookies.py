#!/usr/bin/env python3
"""Export Bland session from default Chrome cookies (fast, ~5s). Chrome must be quit."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from capability import USER_AGENT, VIEWPORT
from capability.voice_ai_dashboards import session_path


def export_cookies() -> int:
    import browser_cookie3 as bc

    out = session_path("bland")
    out.parent.mkdir(parents=True, exist_ok=True)
    seen: set[tuple[str, str, str]] = set()
    cookies = []
    for domain in (".bland.ai", "bland.ai", "app.bland.ai"):
        for c in bc.chrome(domain_name=domain):
            key = (c.domain, c.name, c.path or "/")
            if key in seen:
                continue
            seen.add(key)
            cookies.append(
                {
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path or "/",
                    "expires": c.expires if c.expires else -1,
                    "httpOnly": False,
                    "secure": bool(c.secure),
                    "sameSite": "Lax",
                }
            )
    if not any("session_token" in c["name"] for c in cookies):
        print("No Bland session in Chrome — sign in at app.bland.ai first, quit Chrome, retry.", file=sys.stderr)
        return 1
    out.write_text(json.dumps({"cookies": cookies, "origins": []}, indent=2))
    print(f"exported {len(cookies)} cookies -> {out}")
    return 0


async def verify() -> bool:
    from playwright.async_api import async_playwright

    out = session_path("bland")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport=VIEWPORT, user_agent=USER_AGENT, storage_state=str(out)
        )
        page = await ctx.new_page()
        await page.goto("https://app.bland.ai/dashboard", wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2000)
        body = (await page.inner_text("body"))[:3000].lower()
        ok = "dashboard" in page.url.lower() and "log in to bland" not in body
        print(f"verify logged_in={ok} url={page.url}")
        await browser.close()
        return ok


def main() -> int:
    if subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True).returncode == 0:
        print("Quit Chrome (Cmd+Q) first.", file=sys.stderr)
        return 1
    if export_cookies() != 0:
        return 1
    return 0 if asyncio.run(verify()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
