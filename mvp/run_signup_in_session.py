"""Local harness: run signup_in_session on local Chrome for one or more sites.

  python -m mvp.run_signup_in_session https://linear.app [https://trello.com ...]
      [--headless] [--task "Create an issue"] [--out results/signup_in_session]

Uses local Playwright (channel=chrome, headed on $DISPLAY unless --headless).
Never opens Browserbase. Writes <out>/<host>-<ts>.json and a final.png.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from urllib.parse import urlparse


async def run_one(url: str, *, headless: bool, out: Path, task: str | None, timeout: float) -> dict:
    try:
        # patchright = Playwright with the automation tells removed. Vanilla
        # Playwright Chrome on the box gets "We're unable to verify it's you"
        # from Linear's bot check; patchright gets the email sent.
        from patchright.async_api import async_playwright
    except ImportError:  # pragma: no cover
        from playwright.async_api import async_playwright

    from mvp.signup_in_session import signup_in_session

    host = (urlparse(url).hostname or url).removeprefix("www.")
    stamp = time.strftime("%Y%m%dT%H%M%S")
    async with async_playwright() as p:
        import tempfile

        ctx = await p.chromium.launch_persistent_context(
            tempfile.mkdtemp(prefix="sis-"), channel="chrome", headless=headless,
            no_viewport=True,
        )
        browser = ctx
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            res = await signup_in_session(page, url, {"name": "Sam Rivera"}, timeout_s=timeout)
            await page.screenshot(path=str(out / f"{host}-{stamp}.png"))
            if res.get("ok") and task:
                from mvp.signup_in_session import resume_task_after_signup  # type: ignore

                res["task"] = await resume_task_after_signup(page, url=url, task=task)
                await page.screenshot(path=str(out / f"{host}-{stamp}-task.png"))
        finally:
            await browser.close()
    res["site"] = url
    res["headless"] = headless
    (out / f"{host}-{stamp}.json").write_text(json.dumps(res, indent=2))
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--task")
    ap.add_argument("--timeout", type=float, default=240)
    ap.add_argument("--out", default="results/signup_in_session")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for url in a.urls:
        res = asyncio.run(run_one(url, headless=a.headless, out=out, task=a.task, timeout=a.timeout))
        print(json.dumps({k: res.get(k) for k in ("site", "ok", "reason", "inbox", "elapsed_s", "final_url", "evidence")}), flush=True)
        for s in res.get("steps") or []:
            print("   ", s)


if __name__ == "__main__":
    main()
