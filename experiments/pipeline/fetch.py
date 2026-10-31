"""The one way the pipeline fetches web pages: the fetch ladder (docs/discovery/FETCH_LADDER.md), cheapest first.
  route 1  direct     the machine's own IP (free)
  route 3  dataimpulse residential proxy, US exit (~$1 per GB; credentials in /var/lib/usersim/discovery_keys.json)
  route 4  Camoufox through the same proxy (browser_get), for pages that block routes 1 and 3 (Product Hunt)
A page goes to the next route only when the cheaper one is blocked (403 / 429 / Cloudflare challenge). Apify is never
used here. Every page reports its route and bytes; cost() turns bytes into dollars for the spend log.
Browser scrolling (rare, see incremental.py) runs separately through ph_predict/vm_scroll_lean.py on route 3."""
import json, os, threading, time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from curl_cffi import requests as R

KEYS = "/var/lib/usersim/discovery_keys.json"
USD_PER_GB = {"direct": 0.0, "dataimpulse": 1.0, "dataimpulse_camoufox": 1.0}


def _proxy():
    if not os.path.exists(KEYS):
        return None
    P = json.load(open(KEYS)).get("PROXY_URL")
    u = urlparse(P)
    if "dataimpulse" in (u.hostname or "") and "__cr." not in (u.username or ""):
        P = P.replace(u.username + ":", u.username + "__cr.us:", 1)
    return P


PROXY = _proxy()
ROUTES = [("direct", None)] + ([("dataimpulse", PROXY)] if PROXY else [])


def blocked(r):
    return r.status_code in (403, 429, 503) or "Just a moment" in r.text[:3000]


def get(url, start_route=0):
    rec = {"url": url, "status": 0, "route": None, "bytes": 0, "body": ""}
    for name, proxy in ROUTES[start_route:]:
        for _ in range(2):
            try:
                r = R.get(url, impersonate="chrome", proxies={"https": proxy, "http": proxy} if proxy else None, timeout=60)
            except Exception as e:  # noqa: BLE001
                rec.update(status=-1, route=name, body=str(e)[:200]); continue
            rec["bytes"] += len(r.content); rec.update(status=r.status_code, route=name)
            if not blocked(r):
                rec["body"] = r.text if r.status_code == 200 else ""
                return rec
            break   # blocked on this route: climb the ladder
    return rec


def get_many(urls, threads=8, start_route=0):
    """Fetch many URLs; returns records in input order. Once a route is blocked twice, later pages start one rung up."""
    out, lock, state = [None] * len(urls), threading.Lock(), {"start": start_route, "blocks": 0}

    def one(i):
        rec = get(urls[i], state["start"])
        with lock:
            out[i] = rec
            if rec["route"] != ROUTES[state["start"]][0]:
                state["blocks"] += 1
                if state["blocks"] >= 2 and state["start"] < len(ROUTES) - 1:
                    state["start"] += 1
    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(one, range(len(urls))))
    return out


def cost(recs):
    """Dollars for a batch, by route (bytes counted as received)."""
    by = {}
    for r in recs:
        by[r["route"]] = by.get(r["route"], 0) + r["bytes"]
    return {k: round(v / 1e9 * USD_PER_GB.get(k, 1.0), 4) for k, v in by.items()}, sum(by.values())


def browser_get(url, wait_s=30):
    """Route 4: Camoufox (anti-fingerprint Firefox) through the DataImpulse proxy, images not downloaded (block_images;
    page.route request blocking fails on the Playwright version here).
    For pages that block routes 1 and 3 (Product Hunt). Follows redirects like a person clicking; returns the final
    URL, status, page HTML and bytes transferred."""
    from urllib.parse import unquote
    from camoufox.sync_api import Camoufox
    rec = {"url": url, "final_url": None, "status": 0, "route": "dataimpulse_camoufox", "bytes": 0, "body": ""}
    if not PROXY:
        return rec
    u = urlparse(PROXY)
    proxy = {"server": f"{u.scheme}://{u.hostname}:{u.port}", "username": unquote(u.username or ""), "password": unquote(u.password or "")}
    try:
        return _browser_page(url, rec, proxy, wait_s, Camoufox)
    except Exception as e:  # noqa: BLE001 - a browser that fails to start or crashes: record it, never stop the batch
        rec.update(status=-2, body=str(e)[:200])
        return rec


def _browser_page(url, rec, proxy, wait_s, Camoufox):
    with Camoufox(headless=True, proxy=proxy, geoip=True, block_images=True, os=["windows", "macos"]) as browser:
        page = browser.new_page()
        done = []
        page.on("requestfinished", lambda req: done.append(req))
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            status = resp.status if resp else 0
            deadline = time.time() + wait_s   # as mvp/review_fetch._load: a challenge page turns into the real page by itself
            while time.time() < deadline:
                if "Just a moment" not in (page.title() or "") and "producthunt.com/r/" not in page.url:
                    status = 200 if status in (403, 429, 503) else status
                    break
                page.wait_for_timeout(1500)
            rec.update(status=status, final_url=page.url, body=page.content())
        except Exception as e:  # noqa: BLE001
            rec.update(status=-1, body=str(e)[:200])
        for req in done:
            try:
                z = req.sizes(); rec["bytes"] += sum(max(0, z.get(k, 0)) for k in ("requestHeadersSize", "requestBodySize", "responseHeadersSize", "responseBodySize"))
            except Exception:  # noqa: BLE001
                continue
    return rec
