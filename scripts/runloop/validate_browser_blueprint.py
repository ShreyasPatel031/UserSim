"""Validate the reusable UserSim browser Blueprint with one real page load."""

from __future__ import annotations

import asyncio
import getpass
import json
import shlex

from runloop_api_client import AsyncRunloopSDK


async def main() -> None:
    sdk = AsyncRunloopSDK(bearer_token=getpass.getpass("Runloop API key: "))
    devbox = await sdk.devbox.create(
        name="usersim-blueprint-validation",
        blueprint_name="usersim-browser-v2",
    )
    try:
        code = '''import asyncio, json
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await b.new_page()
        await page.goto("https://www.youtube.com/results?search_query=runloop", wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(2000)
        print(json.dumps({"title": await page.title(), "url": page.url}))
        await b.close()
asyncio.run(main())'''
        result = await devbox.cmd.exec(
            command=f"$HOME/.usersim-browser/bin/python -c {shlex.quote(code)}"
        )
        print(f"devbox_id={devbox.id} exit_code={result.exit_code}")
        print(await result.stdout())
        if result.exit_code != 0:
            print(await result.stderr())
            raise SystemExit(2)
    finally:
        await devbox.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
