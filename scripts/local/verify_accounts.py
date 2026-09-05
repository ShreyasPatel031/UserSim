"""Re-check every product profile and correct identities.json.

The signed-in heuristic used to miss SPA account chrome, so working
accounts were recorded as not_signed_in. This re-probes each saved Chrome
profile and promotes the ones that are really logged in.

    python scripts/local/verify_accounts.py [host ...]
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from mvp.auto_signup import (  # noqa: E402
    PRODUCT_PROFILES,
    SITE_STATES,
    VERIFY_URLS,
    _find_chrome,
    site_state_path,
    verify_signed_in,
)
from mvp.identity import update_identity  # noqa: E402

IDENTITIES = ROOT / "secrets" / "identities.json"


async def _probe(host: str, port: int) -> bool:
    profile = PRODUCT_PROFILES / host
    if not profile.exists():
        return False
    key = host.lower().removeprefix("www.")
    start = (VERIFY_URLS.get(key) or [f"https://www.{key}"])[0]
    proc = subprocess.Popen(
        [
            _find_chrome(),
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile.resolve()}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--window-position=-3000,-3000",
            "--window-size=1440,900",
            start,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    await asyncio.sleep(9)
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await asyncio.sleep(5)
            # SPA shells render the account menu well after domcontentloaded;
            # a single probe reports a live session as logged out.
            ok = False
            for _ in range(3):
                ok = await verify_signed_in(page, host)
                if ok:
                    break
                await asyncio.sleep(4)
            if ok:
                SITE_STATES.mkdir(parents=True, exist_ok=True)
                site_state_path(host).write_text(
                    json.dumps(await ctx.storage_state(), indent=2)
                )
            return ok
    except Exception:
        return False
    finally:
        # Chrome writes cookies on clean shutdown; killing it immediately can
        # drop the session we just confirmed.
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(1)


async def main() -> int:
    hosts = sys.argv[1:]
    if not hosts:
        data = json.loads(IDENTITIES.read_text()).get("products") or {}
        hosts = sorted(data)

    promoted, still = [], []
    for i, host in enumerate(hosts):
        ok = await _probe(host, 9400 + i)
        print(f"  {host:16s} signed_in={ok}", flush=True)
        if ok:
            update_identity(
                f"https://{host}",
                status="signed_up",
                blocker=None,
                profile_dir=str(PRODUCT_PROFILES / host),
            )
            promoted.append(host)
        else:
            still.append(host)

    print(f"\nsigned in ({len(promoted)}): {promoted}")
    print(f"not signed in ({len(still)}): {still}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
