"""Runs on the VM. Opens each URL (stdin) in headless Chromium through the residential proxy and scrolls to the bottom
until nothing new loads (or MAX_SCROLLS), the way a person scrolling the page would. Records every JSON response the
page receives from producthunt.com and the final page HTML. One JSON line per URL: {url, status, scrolls, responses,
html}. Run with:  sudo HOME=/root /opt/usersim/venv/bin/python vm_scroll.py 2 < urls.txt > out.jsonl"""
import asyncio, json, sys
from urllib.parse import urlparse
from playwright.async_api import async_playwright

P = open("/home/agent/php/proxy.txt").read().strip().replace("//auto:", "//groups-RESIDENTIAL,country-US:")
u = urlparse(P)
PROXY = {"server": f"http://{u.hostname}:{u.port}", "username": u.username, "password": u.password}
MAX_SCROLLS, PATIENCE = 400, 6


async def one(browser, url, sem):
    async with sem:
        rec = {"url": url, "status": 0, "scrolls": 0, "responses": []}
        ctx = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", locale="en-US",
                                        viewport={"width": 1280, "height": 1600}, ignore_https_errors=True)
        page = await ctx.new_page()

        async def grab(resp):
            if resp.request.resource_type not in ("xhr", "fetch") or "producthunt.com" not in resp.url:
                return
            try:
                rec["responses"].append({"url": resp.url, "status": resp.status, "body": await resp.json()})
            except Exception:  # noqa: BLE001
                pass
        page.on("response", grab)
        try:
            r = await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            rec["status"] = r.status if r else 0
            await page.wait_for_timeout(3000)
            still, last = 0, -1
            while rec["scrolls"] < MAX_SCROLLS and still < PATIENCE:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1800)
                for label in ("Load more", "Show more", "See more", "View more"):
                    b = page.get_by_role("button", name=label)
                    if await b.count():
                        try:
                            await b.first.click(timeout=2000)
                        except Exception:  # noqa: BLE001
                            pass
                rec["scrolls"] += 1
                h = await page.evaluate("document.body.scrollHeight")
                n = len(rec["responses"])
                still = still + 1 if (h, n) == last else 0
                last = (h, n)
            rec["html"] = (await page.content())[:8_000_000]
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)[:300]
        await ctx.close()
        sys.stdout.write(json.dumps(rec) + "\n"); sys.stdout.flush()


async def main(n):
    urls = [x.strip() for x in sys.stdin if x.strip()]
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, proxy=PROXY)
        sem = asyncio.Semaphore(n)
        await asyncio.gather(*(one(browser, x, sem) for x in urls))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 2))
