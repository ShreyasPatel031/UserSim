"""Runs on the VM. Opens each URL (stdin) in headless Chromium through the residential proxy and scrolls to the bottom
until nothing new loads (or MAX_SCROLLS), the way a person scrolling the page would. Records every JSON response the
page receives from producthunt.com and the final page HTML. One JSON line per URL: {url, status, scrolls, responses,
html}. Run with:  sudo HOME=/root /opt/usersim/venv/bin/python vm_scroll.py 2 < urls.txt > out.jsonl"""
import asyncio, json, sys
from urllib.parse import urlparse
from playwright.async_api import async_playwright

import json as _j; P = _j.load(open("/var/lib/usersim/discovery_keys.json"))["PROXY_URL"]
u = urlparse(P)
PROXY = {"server": f"http://{u.hostname}:{u.port}", "username": (u.username if "__cr." in u.username else u.username + "__cr.us"), "password": u.password}
MAX_SCROLLS, PATIENCE = 400, 6
BYTE_CAP = 25_000_000  # per person: bounds proxy cost for people with tens of thousands of upvotes
import os
OLD = set(open(os.environ["OLD_IDS"]).read().split()) if os.environ.get("OLD_IDS") else set()  # launch ids before the cut-off
ALLOW = tuple(h for h in os.environ.get("ALLOW_HOSTS", "").split(",") if h)  # empty = allow every host
OLD_STOP = 3   # upvotes list is newest first: stop after this many pre-cut-off launches
SHARED = []    # SHARED_CTX=1: one browser context for everyone, so page code is cached after the first person


def voted_ids(o, out=None):
    """ids of upvoted posts inside a GraphQL response (votedPosts edges only, not sidebars)"""
    out = [] if out is None else out
    if isinstance(o, dict):
        vp = o.get("votedPosts")
        if isinstance(vp, dict):
            out += [str(e["node"]["id"]) for e in vp.get("edges") or [] if isinstance(e, dict) and e.get("node")]
        for v in o.values():
            voted_ids(v, out)
    elif isinstance(o, list):
        for v in o:
            voted_ids(v, out)
    return out


async def one(browser, url, sem):
    async with sem:
        rec = {"url": url, "status": 0, "scrolls": 0, "responses": []}
        ctx = SHARED[0] if SHARED else await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", locale="en-US",
                                        viewport={"width": 1280, "height": 1600}, ignore_https_errors=True)
        page = await ctx.new_page()
        def keep(req):
            host = urlparse(req.url).hostname or ""
            return req.resource_type not in ("image", "media", "font") and (not ALLOW or host.endswith(ALLOW))
        await page.route("**/*", lambda r: r.continue_() if keep(r.request) else r.abort())
        rec["bytes"] = 0; rec["hosts"] = {}; rec["old_seen"] = 0
        async def count(resp):
            try:
                n = len(await resp.body())
                rec["bytes"] += n; h = urlparse(resp.url).hostname or ""; rec["hosts"][h] = rec["hosts"].get(h, 0) + n
            except Exception:
                pass
        page.on("response", count)

        async def grab(resp):
            if resp.request.resource_type not in ("xhr", "fetch") or "producthunt.com" not in resp.url:
                return
            try:
                body = await resp.json()
                rec["responses"].append({"url": resp.url, "status": resp.status, "body": body})
                if OLD:
                    rec["old_seen"] += len(OLD.intersection(voted_ids(body)))
            except Exception:  # noqa: BLE001
                pass
        page.on("response", grab)
        try:
            r = await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            rec["status"] = r.status if r else 0
            await page.wait_for_timeout(3000)
            still, last = 0, -1
            while rec["scrolls"] < MAX_SCROLLS and still < PATIENCE and rec["bytes"] < BYTE_CAP and rec["old_seen"] < OLD_STOP:
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
        await (page.close() if SHARED else ctx.close())
        sys.stdout.write(json.dumps(rec) + "\n"); sys.stdout.flush()


async def main(n):
    urls = [x.strip() for x in sys.stdin if x.strip()]
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, proxy=PROXY)
        sem = asyncio.Semaphore(n)
        if os.environ.get("SHARED_CTX") == "1":
            SHARED.append(await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", locale="en-US",
                                                    viewport={"width": 1280, "height": 1600}, ignore_https_errors=True))
        await asyncio.gather(*(one(browser, x, sem) for x in urls))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 2))
