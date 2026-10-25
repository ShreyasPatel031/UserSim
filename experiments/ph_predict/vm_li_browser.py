"""Runs on the VM: a visible Chromium on the virtual display (DISPLAY=:99), through the Apify residential proxy,
with a persistent profile (~agent/php/li_profile) so a login made by hand stays. Opens LinkedIn's sign-in page and
stays open; the user signs in themselves over the noVNC screen."""
import asyncio
from urllib.parse import urlparse
from playwright.async_api import async_playwright

P = open("/home/agent/php/proxy.txt").read().strip().replace("//auto:", "//groups-RESIDENTIAL,country-US:")
u = urlparse(P)
PROXY = {"server": f"http://{u.hostname}:{u.port}", "username": u.username, "password": u.password}


async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            "/home/agent/php/li_profile", headless=False, proxy=PROXY, viewport={"width": 1280, "height": 760},
            locale="en-US", args=["--window-size=1280,800", "--window-position=0,0",
                                  "--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"])  # Google refuses sign-in in browsers flagged as automated
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=90000)
        print("open:", page.url, flush=True)
        await asyncio.Event().wait()  # stay open until stopped


asyncio.run(main())
