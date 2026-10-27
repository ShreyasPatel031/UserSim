"""Browser loads for the gateway: Camoufox opens the page (waiting out a bot challenge), optionally scrolls to the bottom
the way a person would (clicking "Load more" buttons) until nothing new loads, and records the page's XHR / fetch
JSON responses. Images, fonts and media are not downloaded. Every byte is metered, and stop() is asked after each
scroll so a job's budget can end a long scroll early.
"""

from __future__ import annotations

import sys
from typing import Any, Callable
from urllib.parse import urlparse

from fetchgate import ladder

MORE_BUTTONS = ("Load more", "Show more", "See more", "View more", "See more comments", "Show more comments")
MAX_SCROLLS, PATIENCE, SCROLL_WAIT_MS = 400, 6, 1800
MAX_BODY = 2_000_000  # per recorded response


def _registrable(host: str) -> str:
    return ".".join((host or "").lower().split(".")[-2:])


def load(url: str, proxy: str | None, *, scroll: bool = False, meter: dict[str, Any] | None = None,
         stop: Callable[[int], bool] | None = None, max_scrolls: int = MAX_SCROLLS, wait_s: float = 30.0,
         capture: str | None = None) -> dict[str, Any]:
    """{status, html, final_url, scrolls, responses: [{url, method, status, op, body}]}. capture: substring a response
    URL must contain to be recorded (default: the page's own site). meter['bytes'] gets the bytes transferred."""
    from camoufox.sync_api import Camoufox

    meter = meter if meter is not None else {}
    meter.setdefault("bytes", 0)
    site = _registrable(urlparse(url).hostname or "")
    out: dict[str, Any] = {"status": 0, "html": "", "final_url": "", "scrolls": 0, "responses": []}

    finished: list[Any] = []
    seen: list[Any] = []
    done = {"sized": 0, "read": 0}

    def wanted(resp: Any) -> bool:
        if resp.request.resource_type not in ("xhr", "fetch"):
            return False
        if capture is not None:
            return capture in resp.url
        return _registrable(urlparse(resp.url).hostname or "") == site

    def drain() -> None:
        """Meter and record what arrived since last time (handlers only queue: sync calls inside them can hang)."""
        for req in finished[done["sized"]:]:
            try:
                z = req.sizes()
                meter["bytes"] += sum(max(0, z.get(k, 0)) for k in ("requestHeadersSize", "requestBodySize",
                                                                    "responseHeadersSize", "responseBodySize"))
            except Exception:  # noqa: BLE001 - page already gone
                pass
        done["sized"] = len(finished)
        for resp in seen[done["read"]:]:
            req = resp.request
            item: dict[str, Any] = {"url": resp.url, "method": req.method, "status": resp.status, "op": None}
            try:
                item["op"] = (req.post_data_json or {}).get("operationName") if req.method == "POST" else None
            except Exception:  # noqa: BLE001
                pass
            try:
                if len(resp.body()) <= MAX_BODY:
                    item["body"] = resp.json()
            except Exception:  # noqa: BLE001 - not JSON, or gone
                pass
            out["responses"].append(item)
        done["read"] = len(seen)

    with Camoufox(headless="virtual" if sys.platform == "linux" else False, proxy=ladder._proxy_settings(proxy),
                  geoip=bool(proxy), block_images=True, humanize=True, os=["windows", "macos"]) as browser:
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in {"image", "media", "font"}
                   else route.continue_())
        page.on("requestfinished", lambda req: finished.append(req))  # Playwright tags its handlers: no bound builtins
        page.on("response", lambda resp: seen.append(resp) if wanted(resp) else None)
        out["status"], out["html"] = ladder._load(page, url, wait_s)
        drain()
        if scroll and ladder.is_clean(out["status"], out["html"]):
            still, last = 0, None
            while out["scrolls"] < max_scrolls and still < PATIENCE:
                drain()
                if stop and stop(meter["bytes"]):
                    out["stopped"] = "budget"
                    break
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(SCROLL_WAIT_MS)
                for label in MORE_BUTTONS:
                    try:
                        b = page.get_by_role("button", name=label)
                        if b.count():
                            b.first.click(timeout=2000)
                    except Exception:  # noqa: BLE001 - button went away
                        pass
                out["scrolls"] += 1
                now = (page.evaluate("document.body.scrollHeight"), len(seen))
                still = still + 1 if now == last else 0
                last = now
            out["html"] = page.content()
        out["final_url"] = page.url
        page.wait_for_timeout(200)  # let the last requestfinished events land
        drain()
    meter["final_url"] = out["final_url"]
    return out
