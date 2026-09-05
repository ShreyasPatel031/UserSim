"""Run a public-site browser evidence pass in an isolated Runloop Devbox."""

from __future__ import annotations

import json
import os
import shlex
import time
from typing import Any

from runloop_api_client import AsyncRunloopSDK


BLUEPRINT = os.environ.get(
    "RUNLOOP_BROWSER_BLUEPRINT", "runloop/universal-ubuntu-24.04-x86_64"
)
SNAPSHOT = os.environ.get("RUNLOOP_BROWSER_SNAPSHOT", "")


async def run_task_in_devbox(*, url: str, task_prompt: str, agent_id: str) -> dict[str, Any]:
    sdk = AsyncRunloopSDK()
    started = time.monotonic()
    if SNAPSHOT:
        devbox = await sdk.devbox.create_from_snapshot(
            SNAPSHOT, name=f"usersim-{agent_id[:32]}"
        )
    else:
        devbox = await sdk.devbox.create(
            name=f"usersim-{agent_id[:32]}",
            blueprint_name=BLUEPRINT,
        )
    try:
        browser_python = "$HOME/.usersim-browser/bin/python"
        if not SNAPSHOT and BLUEPRINT.startswith("runloop/"):
            setup = await devbox.cmd.exec(
                command=(
                    "python3 -m venv /tmp/usersim-browser && "
                    "/tmp/usersim-browser/bin/pip -q install playwright && "
                    "/tmp/usersim-browser/bin/playwright install --with-deps chromium"
                )
            )
            if setup.exit_code != 0:
                raise RuntimeError(f"Runloop browser setup failed: {(await setup.stderr())[-1000:]}")
            browser_python = "/tmp/usersim-browser/bin/python"

        script = f'''import asyncio, base64, json
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(viewport={{"width": 1280, "height": 800}})
        await page.goto({url!r}, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(3000)
        body = (await page.locator("body").inner_text())[:12000]
        links = await page.locator("a[href]").evaluate_all("els => els.slice(0, 60).map(a => ({{text: (a.innerText || '').trim().slice(0, 160), href: a.href}}))")
        screenshot = await page.screenshot(type="jpeg", quality=58, full_page=False)
        screenshot_url = "data:image/jpeg;base64," + base64.b64encode(screenshot).decode("ascii")
        print(json.dumps({{"url": page.url, "title": await page.title(), "body_text": body, "links": links, "screenshot_url": screenshot_url, "task": {task_prompt!r}}}))
        await browser.close()

asyncio.run(main())'''
        execution = await devbox.cmd.exec(
            command=f"{browser_python} -c {shlex.quote(script)}"
        )
        if execution.exit_code != 0:
            raise RuntimeError(f"Runloop browser failed: {(await execution.stderr())[-1000:]}")
        evidence = None
        for line in reversed((await execution.stdout()).splitlines()):
            try:
                evidence = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        if not evidence:
            raise RuntimeError("Runloop browser returned no JSON evidence")
        evidence["devbox_id"] = devbox.id
        evidence["elapsed_s"] = round(time.monotonic() - started, 3)
        return evidence
    finally:
        await devbox.shutdown()
