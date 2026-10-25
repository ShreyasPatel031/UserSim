"""In-house fetching of G2 / Capterra / Product Hunt review pages (to replace Apify), through a residential proxy.

Product Hunt (Cloudflare) and G2 (DataDome) block data-centre IPs outright, so pages go through PROXY_URL (a rotating
residential proxy, e.g. DataImpulse) when it is set. curl_cffi sends Chrome's TLS/HTTP2 fingerprint, which plain
HTTP clients do not; no browser is needed when the protection lets that through.

probe() reports, for one review URL, what each way of fetching gets back (status, title, size, whether a bot
challenge was served), so the approach can be measured on the real sites before parsers are built on it.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import unquote, urlparse

# Only review pages on these sites: the probe must not become an open proxy.
ALLOWED_HOSTS = ("producthunt.com", "g2.com", "capterra.com")
_CHALLENGE_RE = re.compile(r"just a moment|performing security verification|cf-chl|challenge-platform|captcha-delivery|"
                           r"datadome|access denied|attention required|please enable js", re.I)


def allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return urlparse(url).scheme == "https" and any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def _summary(status: int, html: str, started: float) -> dict[str, Any]:
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", html or "")
    title_text = re.sub(r"\s+", " ", title.group(1)).strip()[:120] if title else ""
    head = (html or "")[:20000]
    return {"status": status, "title": title_text, "kb": round(len(html or "") / 1024),
            "challenge": bool(status in (403, 429, 503) or _CHALLENGE_RE.search(title_text) or
                              (len(html or "") < 20000 and _CHALLENGE_RE.search(head))),
            "ms": int((time.time() - started) * 1000)}


def fetch(url: str, proxy: str | None, *, impersonate: str | None = "chrome", timeout: float = 45.0) -> tuple[int, str]:
    """GET one page. impersonate=None uses a plain client (for comparison)."""
    if impersonate:
        from curl_cffi import requests as creq

        r = creq.get(url, impersonate=impersonate, proxies={"http": proxy, "https": proxy} if proxy else None,
                     timeout=timeout, headers={"Accept-Language": "en-US,en;q=0.9"})
        return r.status_code, r.text or ""
    import httpx

    with httpx.Client(proxy=proxy, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                             "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                               "Accept-Language": "en-US,en;q=0.9"}) as c:
        r = c.get(url)
        return r.status_code, r.text or ""


# G2 (DataDome) and Capterra (Cloudflare) want a real browser that runs their JavaScript checks. The VM's deploy
# script is installed once and does not update from the repo, so Chromium is installed by the app on first use.
_BROWSER_LOCK = threading.Lock()
_BROWSER_STATE: dict[str, Any] = {}
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/131.0.0.0 Safari/537.36")
_HIDE_AUTOMATION = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || {runtime: {}};
"""


def ensure_browser() -> dict[str, Any]:
    """Make sure Playwright's Chromium is installed (once per process). {ok, how, error}."""
    with _BROWSER_LOCK:
        if _BROWSER_STATE.get("ok"):
            return dict(_BROWSER_STATE)
        from playwright.sync_api import sync_playwright

        def launches() -> str:
            try:
                with sync_playwright() as pw:
                    pw.chromium.launch(headless=True).close()
                return ""
            except Exception as exc:  # noqa: BLE001
                return repr(exc)[:300]
        err = launches()
        if not err:
            _BROWSER_STATE.update(ok=True, how="already installed")
            return dict(_BROWSER_STATE)
        steps = []
        for cmd in ([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
                    [sys.executable, "-m", "playwright", "install", "chromium"]):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            steps.append(f"{' '.join(cmd[3:])}: exit {r.returncode} {(r.stderr or r.stdout)[-200:]}")
            err = launches()
            if not err:
                _BROWSER_STATE.update(ok=True, how="installed: " + steps[-1][:80])
                return dict(_BROWSER_STATE)
        _BROWSER_STATE.update(ok=False, how="; ".join(steps)[-400:], error=err)
        return dict(_BROWSER_STATE)


def _proxy_settings(proxy: str | None) -> dict[str, str] | None:
    if not proxy:
        return None
    u = urlparse(proxy)
    out = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
    if u.username:
        out.update(username=unquote(u.username), password=unquote(u.password or ""))
    return out


def browser_fetch(url: str, proxy: str | None, *, wait_s: float = 30.0) -> tuple[int, str]:
    """Load a page in headless Chromium (through the proxy), waiting for a bot challenge to clear. Images, fonts and
    media are not downloaded (proxy traffic is paid per GB)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, proxy=_proxy_settings(proxy),
                                     args=["--disable-blink-features=AutomationControlled"])
        try:
            ctx = browser.new_context(user_agent=_UA, locale="en-US", viewport={"width": 1366, "height": 900},
                                      timezone_id="America/New_York")
            ctx.add_init_script(_HIDE_AUTOMATION)
            ctx.route("**/*", lambda route: route.abort() if route.request.resource_type in {"image", "media", "font"}
                      else route.continue_())
            page = ctx.new_page()
            resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            status = resp.status if resp else 0
            deadline = time.time() + wait_s
            while time.time() < deadline:  # challenge pages reload themselves into the real page once passed
                html = page.content()
                if not _CHALLENGE_RE.search(page.title() or "") and len(html) > 20000:
                    return 200 if status in (403, 429, 503) else status, html
                page.wait_for_timeout(1500)
            return status, page.content()
        finally:
            browser.close()


def probe(url: str, proxy: str | None) -> dict[str, Any]:
    """What each fetch method gets for one review URL, with and without the proxy."""
    if not allowed(url):
        raise ValueError(f"only https review pages on {', '.join(ALLOWED_HOSTS)}")
    out: dict[str, Any] = {"url": url, "proxy": bool(proxy)}
    tries = [("chrome_fingerprint_via_proxy", proxy, "chrome"), ("plain_via_proxy", proxy, None)] if proxy else []
    tries.append(("chrome_fingerprint_direct", None, "chrome"))
    setup = ensure_browser()
    out["browser_setup"] = setup
    if setup.get("ok"):
        tries.insert(0, ("browser_via_proxy" if proxy else "browser_direct", proxy, "browser"))
    for name, px, imp in tries:
        t = time.time()
        try:
            status, html = browser_fetch(url, px) if imp == "browser" else fetch(url, px, impersonate=imp)
            out[name] = _summary(status, html, t)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            msg = re.sub(r"//[^@\s/]+@", "//<redacted>@", repr(exc))  # proxy errors can echo user:pass
            out[name] = {"error": msg[:300], "ms": int((time.time() - t) * 1000)}
    return out
