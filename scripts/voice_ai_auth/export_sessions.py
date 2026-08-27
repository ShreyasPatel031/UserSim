#!/usr/bin/env python3
"""Export voice-AI dashboard sessions from default Chrome (Cmd+Q Chrome first)."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from capability import USER_AGENT, VIEWPORT
from capability.voice_ai_dashboards import DASHBOARD_BY_KEY, DASHBOARDS, session_path


def export_key(key: str) -> int:
    import browser_cookie3 as bc

    dash = DASHBOARD_BY_KEY[key]
    domains = dash.cookie_domains or (f".{key}.com", key)
    out = session_path(key)
    out.parent.mkdir(parents=True, exist_ok=True)
    seen: set[tuple[str, str, str]] = set()
    cookies = []
    for domain in domains:
        for c in bc.chrome(domain_name=domain):
            k = (c.domain, c.name, c.path or "/")
            if k in seen:
                continue
            seen.add(k)
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
    has_session = any(
        any(hint in c["name"].lower() for hint in dash.session_cookie_hints)
        for c in cookies
    )
    if len(cookies) < 2 and not has_session:
        print(f"{key}: no session cookies — sign in at {dash.login_url}", file=sys.stderr)
        return 1
    out.write_text(json.dumps({"cookies": cookies, "origins": []}, indent=2))
    print(f"{key}: exported {len(cookies)} cookies -> {out}")
    return 0


async def verify_key(key: str) -> bool:
    from playwright.async_api import async_playwright

    dash = DASHBOARD_BY_KEY[key]
    sp = session_path(key)
    if not sp.is_file():
        return False
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport=VIEWPORT, user_agent=USER_AGENT, storage_state=str(sp)
        )
        page = await ctx.new_page()
        await page.goto(dash.dashboard_url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2000)
        body = (await page.inner_text("body"))[:4000].lower()
        login = any(h in body for h in dash.login_body_hints)
        logged_url = any(h in page.url.lower() for h in dash.logged_in_url_hints)
        logged_body = any(h in body for h in dash.logged_in_body_hints)
        ok = (logged_url or logged_body) and not login and "/login" not in page.url.lower()
        print(f"{key}: verify logged_in={ok} url={page.url}")
        await browser.close()
        return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="Comma keys: retell,vapi,bland")
    args = ap.parse_args()
    if subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True).returncode == 0:
        print("Quit Chrome (Cmd+Q) first.", file=sys.stderr)
        return 1
    keys = [k.strip() for k in args.only.split(",") if k.strip()] or [d.key for d in DASHBOARDS]
    rc = 0
    for key in keys:
        if key not in DASHBOARD_BY_KEY:
            print(f"Unknown key {key}", file=sys.stderr)
            rc = 1
            continue
        if export_key(key) != 0:
            rc = 1
            continue
        if not asyncio.run(verify_key(key)):
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
