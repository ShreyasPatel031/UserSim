"""In-house fetching of G2 / Capterra / Product Hunt review pages (to replace Apify), through a residential proxy.

Product Hunt (Cloudflare) and G2 (DataDome) block data-centre IPs outright, so pages go through PROXY_URL (a rotating
residential proxy, e.g. DataImpulse) when it is set. curl_cffi sends Chrome's TLS/HTTP2 fingerprint, which plain
HTTP clients do not; no browser is needed when the protection lets that through.

probe() reports, for one review URL, what each way of fetching gets back (status, title, size, whether a bot
challenge was served), so the approach can be measured on the real sites before parsers are built on it.
"""

from __future__ import annotations

import os
import re
import shutil
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


_DISPLAY_LOCK = threading.Lock()


def ensure_display() -> str:
    """A virtual X display for headed Chromium (Xvfb on :99, installed with apt if missing). '' when unavailable."""
    with _DISPLAY_LOCK:
        if os.environ.get("DISPLAY"):
            return os.environ["DISPLAY"]
        if not shutil.which("Xvfb"):
            subprocess.run(["apt-get", "install", "-y", "-q", "xvfb"], capture_output=True, timeout=300)
        if not shutil.which("Xvfb"):
            return ""
        subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1366x900x24", "-nolisten", "tcp"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1.5)
        os.environ["DISPLAY"] = ":99"
        return ":99"


def browser_fetch(url: str, proxy: str | None, *, wait_s: float = 30.0, headed: bool = False) -> tuple[int, str]:
    """Load a page in Chromium (through the proxy), waiting for a bot challenge to clear. Headed mode runs a normal
    browser window on a virtual display, with Chromium's own user agent (no headless tells to patch over). Images,
    fonts and media are not downloaded (proxy traffic is paid per GB)."""
    from playwright.sync_api import sync_playwright

    if headed and not ensure_display():
        raise RuntimeError("no X display for headed Chromium (Xvfb missing and could not be installed)")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed, proxy=_proxy_settings(proxy),
                                     args=["--disable-blink-features=AutomationControlled"])
        try:
            opts: dict[str, Any] = {"locale": "en-US", "viewport": {"width": 1366, "height": 900},
                                    "timezone_id": "America/New_York"}
            if not headed:
                opts["user_agent"] = _UA
            ctx = browser.new_context(**opts)
            if not headed:
                ctx.add_init_script(_HIDE_AUTOMATION)
            ctx.route("**/*", lambda route: route.abort() if route.request.resource_type in {"image", "media", "font"}
                      else route.continue_())
            return _load(ctx.new_page(), url, wait_s)
        finally:
            browser.close()


def _load(page: Any, url: str, wait_s: float) -> tuple[int, str]:
    """Open url and wait for a bot challenge page to turn into the real page (they reload themselves once passed)."""
    resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
    status = resp.status if resp else 0
    deadline = time.time() + wait_s
    while time.time() < deadline:
        html = page.content()
        if not _CHALLENGE_RE.search(page.title() or "") and len(html) > 20000:
            return 200 if status in (403, 429, 503) else status, html
        page.wait_for_timeout(1500)
    return status, page.content()


_TOOLS: dict[str, Any] = {}


def ensure_tool(name: str) -> dict[str, Any]:
    """Download the browser a stealth tool drives, once per process: 'patchright' (patched Chromium) or 'camoufox'
    (anti-fingerprint Firefox, pinned to 0.4.11 whose browser builds are published)."""
    with _BROWSER_LOCK:
        if name in _TOOLS:
            return _TOOLS[name]
        cmd = {"patchright": [sys.executable, "-m", "patchright", "install", "chromium"],
               "camoufox": [sys.executable, "-m", "camoufox", "fetch"]}[name]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            _TOOLS[name] = {"ok": r.returncode == 0, "how": (r.stderr or r.stdout)[-200:]}
        except Exception as exc:  # noqa: BLE001
            _TOOLS[name] = {"ok": False, "how": repr(exc)[:200]}
        return _TOOLS[name]


def patchright_fetch(url: str, proxy: str | None, *, wait_s: float = 30.0) -> tuple[int, str]:
    """Patchright (Playwright with Chromium's automation leaks patched), headed on the virtual display, no injected
    scripts or user-agent override (those are themselves detectable)."""
    from patchright.sync_api import sync_playwright

    if not ensure_display():
        raise RuntimeError("no X display")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, proxy=_proxy_settings(proxy))
        try:
            ctx = browser.new_context(locale="en-US", timezone_id="America/New_York", no_viewport=True)
            return _load(ctx.new_page(), url, wait_s)
        finally:
            browser.close()


def camoufox_fetch(url: str, proxy: str | None, *, wait_s: float = 30.0) -> tuple[int, str]:
    """Camoufox: Firefox with fingerprints spoofed at the C++ level, on its own virtual display; locale and timezone
    follow the proxy's exit IP (geoip)."""
    from camoufox.sync_api import Camoufox

    with Camoufox(headless="virtual", proxy=_proxy_settings(proxy), geoip=bool(proxy), block_images=True,
                  humanize=True, os=["windows", "macos"]) as browser:
        return _load(browser.new_page(), url, wait_s)


def probe(url: str, proxy: str | None) -> dict[str, Any]:
    """What each fetch method gets for one review URL, with and without the proxy."""
    if not allowed(url):
        raise ValueError(f"only https review pages on {', '.join(ALLOWED_HOSTS)}")
    out: dict[str, Any] = {"url": url, "proxy": bool(proxy)}
    tries = [("chrome_fingerprint_via_proxy", proxy, "chrome"), ("plain_via_proxy", proxy, None)] if proxy else []
    tries.append(("chrome_fingerprint_direct", None, "chrome"))
    setup = ensure_browser()
    out["browser_setup"] = setup
    via = "via_proxy" if proxy else "direct"
    stealth = []
    for tool in ("camoufox", "patchright"):
        out[f"{tool}_setup"] = ensure_tool(tool)
        if out[f"{tool}_setup"]["ok"]:
            stealth.append((f"{tool}_{via}", proxy, tool))
    if setup.get("ok"):
        stealth += [(f"headed_chromium_{via}", proxy, "headed"), (f"headless_chromium_{via}", proxy, "browser")]
    tries[:0] = stealth
    for name, px, imp in tries:
        t = time.time()
        try:
            if imp in ("browser", "headed"):
                status, html = browser_fetch(url, px, headed=imp == "headed")
            elif imp == "patchright":
                status, html = patchright_fetch(url, px)
            elif imp == "camoufox":
                status, html = camoufox_fetch(url, px)
            else:
                status, html = fetch(url, px, impersonate=imp)
            out[name] = _summary(status, html, t)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            msg = re.sub(r"//[^@\s/]+@", "//<redacted>@", repr(exc))  # proxy errors can echo user:pass
            out[name] = {"error": msg[:300], "ms": int((time.time() - t) * 1000)}
    return out
