"""Runs on the VM. Opens each URL (stdin, one per line) in headless Chromium through the Apify residential proxy,
scrolls and clicks "more comments" a few times, and records every JSON response from Product Hunt's own data
endpoint. Writes one JSON line per URL to stdout: {url, status, responses: [...]}.
Used as:  ssh vm 'python ~/php/vmbrowse.py 3' < urls.txt > out.jsonl"""
import asyncio, json, os, sys
from urllib.parse import urlparse
from playwright.async_api import async_playwright

P = open("/home/agent/php/proxy.txt").read().strip().replace("//auto:", "//groups-RESIDENTIAL,country-US:")
u = urlparse(P)
PROXY = {"server": f"http://{u.hostname}:{u.port}", "username": u.username, "password": u.password}


async def one(browser, url, sem):
    async with sem:
        rec = {"url": url, "status": 0, "responses": []}
        ctx = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", locale="en-US",
                                        ignore_https_errors=True)
        page = await ctx.new_page()

        async def grab(resp):
            if resp.request.resource_type not in ("xhr", "fetch") or "producthunt.com" not in resp.url:
                return
            item = {"url": resp.url, "method": resp.request.method, "status": resp.status}
            try:
                item["op"] = (resp.request.post_data_json or {}).get("operationName") if resp.request.method == "POST" else None
            except Exception:  # noqa: BLE001
                item["op"] = None
            try:
                item["body"] = await resp.json()
            except Exception:  # noqa: BLE001
                pass
            rec["responses"].append(item)
        page.on("response", grab)
        try:
            r = await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            rec["status"] = r.status if r else 0
            for _ in range(6):
                await page.mouse.wheel(0, 4000)
                await page.wait_for_timeout(1500)
                for label in ("See more comments", "Show more comments", "Load more", "View more"):
                    b = page.get_by_text(label, exact=False)
                    if await b.count():
                        try:
                            await b.first.click(timeout=3000)
                        except Exception:  # noqa: BLE001
                            pass
            html = await page.content()
            rec["html_len"] = len(html)
            rec["html"] = html[:3_000_000]
        except Exception as e:  # noqa: BLE001
            rec["error"] = str(e)[:200]
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
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3))
