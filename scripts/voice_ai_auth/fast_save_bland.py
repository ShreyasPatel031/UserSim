#!/usr/bin/env python3
"""Save Bland product session via Chrome CDP (dedicated profile, phone OTP works)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from capability.voice_ai_dashboards import DASHBOARD_BY_KEY, PROFILE_DIR, session_path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CDP_PORT = 9333
CDP_HTTP = f"http://127.0.0.1:{CDP_PORT}"
DASH = DASHBOARD_BY_KEY["bland"]


def kill_chrome():
    subprocess.run(["pkill", "-x", "Google Chrome"], check=False)
    time.sleep(2)


def cdp_endpoint() -> str | None:
    try:
        with urllib.request.urlopen(f"{CDP_HTTP}/json/version", timeout=2) as resp:
            data = json.loads(resp.read().decode())
        return data.get("webSocketDebuggerUrl") or CDP_HTTP
    except Exception:
        return None


def _logged_in(url: str, body: str) -> bool:
    low_url, low_body = url.lower(), body.lower()
    if any(h in low_url for h in DASH.logged_in_url_hints):
        return True
    if any(h in low_body for h in DASH.logged_in_body_hints):
        return True
    if "log in to bland" in low_body or "sign in with google" in low_body:
        return False
    return "dashboard" in low_url and "/login" not in low_url


async def save(wait_s: float = 120) -> int:
    from playwright.async_api import async_playwright

    kill_chrome()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    out = session_path("bland")
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"Chrome opening → {DASH.login_url}")
    print("Sign in with PHONE (Get code) — Google often blocks automation.")

    proc = subprocess.Popen(
        [
            CHROME,
            f"--user-data-dir={PROFILE_DIR}",
            f"--remote-debugging-port={CDP_PORT}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            DASH.login_url,
        ],
    )

    try:
        endpoint = None
        for i in range(40):
            endpoint = cdp_endpoint()
            if endpoint:
                print(f"CDP ready ({i * 0.5:.0f}s)")
                break
            await asyncio.sleep(0.5)
        if not endpoint:
            print("CDP failed", file=sys.stderr)
            return 1

        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(endpoint)
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()

            deadline = time.monotonic() + wait_s
            logged = False
            while time.monotonic() < deadline:
                try:
                    body = (await page.inner_text("body"))[:6000]
                    if _logged_in(page.url, body):
                        logged = True
                        break
                except Exception:
                    pass
                await asyncio.sleep(2)

            body = (await page.inner_text("body"))[:6000]
            logged = logged or _logged_in(page.url, body)
            print(f"url={page.url} logged_in={logged}")

            await context.storage_state(path=str(out))
            await browser.close()

        if not logged:
            return 1
        print(f"Saved {out} ({out.stat().st_size} bytes)")
        return 0
    finally:
        kill_chrome()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    wait = float(sys.argv[1] if len(sys.argv) > 1 else 120)
    return asyncio.run(save(wait))


if __name__ == "__main__":
    raise SystemExit(main())
