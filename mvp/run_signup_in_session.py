"""Prove signup_in_session on the five e2e sites. One Browserbase session, owner=signup.

Does not print mailboxes or passwords. Writes alias_tag, reason, and elapsed only.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

SITES = [
    "https://linear.app",
    "https://trello.com",
    "https://asana.com",
    "https://miro.com",
    "https://www.tldraw.com",
]
OUT = Path("results/signup_in_session/prove.json")


async def _run(repeats: int) -> dict:
    os.environ["BROWSERBASE_THROTTLE"] = "1"
    os.environ["BROWSERBASE_MAX_CONCURRENT"] = "1"
    from playwright.async_api import async_playwright

    from capability.browserbase_client import close_session, create_session
    from mvp.signup_in_session import signup_in_session

    sess = create_session(
        proxies=False,
        solve_captchas=True,
        advanced_stealth=False,
        owner="signup",
        study_id="signup-in-session",
    )
    rows: list[dict] = []
    print(f"session {sess.id}", flush=True)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(sess.connect_url)
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            for n in range(repeats):
                for site in SITES:
                    result = await signup_in_session(page, site, None)
                    row = {
                        "site": site,
                        "run": n + 1,
                        "ok": result.get("ok"),
                        "reason": result.get("reason"),
                        "elapsed_s": result.get("elapsed_s"),
                        "alias_tag": result.get("alias_tag"),
                        "steps": result.get("steps"),
                    }
                    rows.append(row)
                    print(
                        f"RESULT site={site} run={n+1} ok={row['ok']} "
                        f"reason={row['reason']} elapsed={row['elapsed_s']} "
                        f"tag={row['alias_tag']}",
                        flush=True,
                    )
            await browser.close()
    finally:
        close_session(sess.id)
        print(f"released {sess.id}", flush=True)
    summary: dict[str, dict] = {}
    for site in SITES:
        mine = [r for r in rows if r["site"] == site]
        passed = sum(1 for r in mine if r["ok"])
        summary[site] = {
            "passed": passed,
            "runs": len(mine),
            "reasons": [r["reason"] for r in mine],
        }
    return {"session_released": True, "summary": summary, "rows": rows}


def main() -> None:
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    if len(sys.argv) > 2:
        global SITES
        want = {a.lower().removeprefix("www.") for a in sys.argv[2:] }
        SITES = [s for s in SITES if any(h in s for h in want)]
    payload = asyncio.run(_run(repeats))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload["summary"], indent=2), flush=True)


if __name__ == "__main__":
    main()
