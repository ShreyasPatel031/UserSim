"""Local end-to-end: the real step loop hits needs_account, signs up in the same
page, and finishes the account task signed in. Local patchright Chrome only.

  python -m mvp.run_signup_task_local https://linear.app "Create an issue titled Signup smoke test"
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse


async def main(url: str, task: str, headless: bool = False) -> dict:
    from patchright.async_api import async_playwright

    from mvp.a11y_agent import complete_task_on_page, signup_and_resume

    out = Path("results/signup_in_session")
    out.mkdir(parents=True, exist_ok=True)
    host = (urlparse(url).hostname or "site").removeprefix("www.")
    stamp = time.strftime("%Y%m%dT%H%M%S")
    t0 = time.monotonic()
    deadline = t0 + 480
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            tempfile.mkdtemp(prefix="sis-task-"), channel="chrome", headless=headless, no_viewport=True,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            first = await complete_task_on_page(page, task=task, url=url, deadline=deadline, agent_id="local")
            su = None
            outcome = first
            if first.get("stop_reason") == "needs_account":
                su, outcome = await signup_and_resume(
                    page, task=task, url=url, persona={"name": "Sam Rivera"}, outcome=first,
                    deadline=deadline, agent_id="local",
                )
            await page.wait_for_timeout(1500)
            await page.screenshot(path=str(out / f"task-{host}-{stamp}.png"))
            res = {
                "site": url, "task": task,
                "first_stop": first.get("stop_reason"), "signup_url": first.get("signup_url"),
                "signup": {k: (su or {}).get(k) for k in ("ok", "reason", "inbox", "elapsed_s", "final_url", "evidence")},
                "stop_reason": outcome.get("stop_reason"),
                "final_url": str(page.url),
                "elapsed_s": round(time.monotonic() - t0, 1),
                "actions": [str(r.get("action")) for r in outcome.get("trace") or [] if isinstance(r, dict)],
                "signup_steps": (su or {}).get("steps"),
                "screenshot": str(out / f"task-{host}-{stamp}.png"),
            }
        finally:
            await ctx.close()
    (out / f"task-{host}-{stamp}.json").write_text(json.dumps(res, indent=2))
    return res


if __name__ == "__main__":
    r = asyncio.run(main(sys.argv[1], sys.argv[2], "--headless" in sys.argv))
    print(json.dumps({k: v for k, v in r.items() if k != "signup_steps"}, indent=1))
