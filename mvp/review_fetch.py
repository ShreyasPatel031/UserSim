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
# Cloudflare localises its challenge title to the visitor's language ("Un instant…" from a French exit IP).
_CHALLENGE_RE = re.compile(r"just a moment|performing security verification|cf-chl|challenge-platform|captcha-delivery|"
                           r"datadome|access denied|attention required|please enable js|un instant|einen moment|"
                           r"un momento|um momento|even geduld|chwileczk|одну минуту|しばらくお待ち", re.I)


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


def _intercepting(proxy: str | None) -> bool:
    """Unblocking proxies (Apify's UNBLOCKER group) decrypt and re-encrypt HTTPS themselves, so their certificate is
    not the site's; certificate checks are relaxed for those proxies only."""
    return bool(proxy) and "unblocker" in proxy.lower()


# ---------------------------------------------------------------- our own unblocker (prototype)
#
# What a commercial unblocker does, in its smallest form: a sticky residential IP (DataImpulse ports 10000-20000 keep
# one IP for ~30 min), the bot challenge solved once on that IP by CapSolver (Cloudflare: AntiCloudflareTask ->
# cf_clearance; DataDome: DatadomeSliderTask -> datadome cookie), then the clearance cookie and user agent reused
# for the following requests from the same IP.

_CAPSOLVER = "https://api.capsolver.com"
_DD_RE = re.compile(r"var\s+dd\s*=\s*(\{.*?\})", re.S)


def sticky_proxy(proxy: str, slot: int) -> str:
    """The same DataImpulse login on sticky port 10000+slot (one exit IP per port for ~30 min), US exits."""
    u = urlparse(proxy)
    user = u.username or ""
    if "__cr." not in user:
        user += "__cr.us"
    return f"{u.scheme}://{user}:{u.password}@{u.hostname}:{10000 + slot % 10000}"


def _capsolver_proxy(proxy: str) -> str:
    u = urlparse(proxy)
    return f"{u.hostname}:{u.port}:{unquote(u.username or '')}:{unquote(u.password or '')}"


def capsolver_solve(task: dict[str, Any], *, wait_s: float = 120.0) -> dict[str, Any]:
    """One CapSolver task (CAPSOLVER_API_KEY), polled until ready. Returns the solution dict."""
    import requests

    key = (os.environ.get("CAPSOLVER_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("CAPSOLVER_API_KEY missing")
    r = requests.post(f"{_CAPSOLVER}/createTask", json={"clientKey": key, "task": task}, timeout=30).json()
    if r.get("errorId"):
        raise RuntimeError(f"capsolver createTask: {r.get('errorCode')} {r.get('errorDescription')}")
    if r.get("status") == "ready":
        return r.get("solution") or {}
    task_id = r.get("taskId")
    if not task_id:
        raise RuntimeError(f"capsolver createTask returned no taskId: {str(r)[:150]}")
    deadline = time.time() + wait_s
    while time.time() < deadline:
        time.sleep(3)
        r = requests.post(f"{_CAPSOLVER}/getTaskResult", json={"clientKey": key, "taskId": task_id}, timeout=30).json()
        if r.get("errorId"):
            raise RuntimeError(f"capsolver getTaskResult: {r.get('errorCode')} {r.get('errorDescription')}")
        if r.get("status") == "ready":
            return r.get("solution") or {}
    raise RuntimeError("capsolver: no solution in time")


def _cookie_header(solution: dict[str, Any]) -> str:
    """CapSolver returns cookies as a dict, a list of {name, value}, or a 'a=b; c=d' string."""
    c = solution.get("cookies") or solution.get("cookie") or {}
    if isinstance(c, dict):
        return "; ".join(f"{k}={v}" for k, v in c.items())
    if isinstance(c, list):
        return "; ".join(f"{x.get('name')}={x.get('value')}" for x in c if isinstance(x, dict))
    return str(c).split(";")[0] if "datadome=" in str(c) else str(c)


def own_unblock(url: str, proxy: str, *, slots: tuple[int, ...] = (1, 2, 3)) -> dict[str, Any]:
    """Fetch url through our own unblocker: try a few sticky IPs; on a Cloudflare or DataDome challenge, solve it
    with CapSolver on that IP and refetch with the clearance cookie. Reports each step (never the cookie)."""
    from curl_cffi import requests as creq

    steps: list[dict[str, Any]] = []
    for slot in slots:
        px = sticky_proxy(proxy, slot)
        proxies = {"http": px, "https": px}
        t = time.time()
        try:
            r = creq.get(url, impersonate="chrome", proxies=proxies, timeout=45)
        except Exception as exc:  # noqa: BLE001
            steps.append({"slot": slot, "error": re.sub(r"//[^@\s/]+@", "//<redacted>@", repr(exc))[:150]})
            continue
        s0 = _summary(r.status_code, r.text, t)
        step: dict[str, Any] = {"slot": slot, "first": s0}
        if not s0["challenge"]:
            steps.append(step)
            return {"ok": True, "status": r.status_code, "html": r.text, "steps": steps}
        try:
            dd = _DD_RE.search(r.text)
            if dd:  # DataDome (G2)
                import json as _json

                info = _json.loads(dd.group(1).replace("'", '"'))
                if info.get("t") == "bv":
                    step["solve"] = "DataDome banned this IP (t=bv); next IP"
                    steps.append(step)
                    continue
                cid = r.cookies.get("datadome") or ""
                captcha_url = (f"https://{info.get('host', 'geo.captcha-delivery.com')}/captcha/?initialCid={info.get('cid')}"
                               f"&hash={info.get('hsh')}&cid={cid}&t={info.get('t')}&referer={url}&s={info.get('s')}"
                               f"&e={info.get('e', '')}")
                ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                sol = capsolver_solve({"type": "DatadomeSliderTask", "websiteURL": url, "captchaUrl": captcha_url,
                                       "userAgent": ua, "proxy": _capsolver_proxy(px)})
            else:  # Cloudflare (Capterra)
                ua = None
                sol = capsolver_solve({"type": "AntiCloudflareTask", "websiteURL": url, "proxy": _capsolver_proxy(px)})
                ua = sol.get("userAgent")
            step["solution_keys"] = sorted(sol.keys())
            headers = {"Cookie": _cookie_header(sol), "Accept-Language": "en-US,en;q=0.9"}
            if ua or sol.get("userAgent"):
                headers["User-Agent"] = sol.get("userAgent") or ua
            t = time.time()
            r2 = creq.get(url, impersonate="chrome", proxies=proxies, headers=headers, timeout=45)
            step["after_solve"] = _summary(r2.status_code, r2.text, t)
            steps.append(step)
            if not step["after_solve"]["challenge"]:
                return {"ok": True, "status": r2.status_code, "html": r2.text, "steps": steps}
        except Exception as exc:  # noqa: BLE001
            step["solve_error"] = re.sub(r"//[^@\s/]+@", "//<redacted>@", repr(exc))[:200]
            steps.append(step)
    return {"ok": False, "status": 0, "html": "", "steps": steps}


def apify_proxy(group: str, country: str = "US") -> str:
    """Apify Proxy URL for one group (UNBLOCKER, RESIDENTIAL), built from the saved Apify token."""
    import requests

    from mvp import discovery

    token = discovery.apify_token()
    if not token:
        raise RuntimeError("APIFY_TOKEN missing")
    pw = requests.get("https://api.apify.com/v2/users/me", headers={"Authorization": f"Bearer {token}"},
                      timeout=20).json()["data"]["proxy"]["password"]
    user = f"groups-{group}" + (f",country-{country}" if country and group != "UNBLOCKER" else "")
    return f"http://{user}:{pw}@proxy.apify.com:8000"


def fetch(url: str, proxy: str | None, *, impersonate: str | None = "chrome", timeout: float = 45.0) -> tuple[int, str]:
    """GET one page. impersonate=None uses a plain client (for comparison)."""
    if impersonate:
        from curl_cffi import requests as creq

        r = creq.get(url, impersonate=impersonate, proxies={"http": proxy, "https": proxy} if proxy else None,
                     timeout=timeout, headers={"Accept-Language": "en-US,en;q=0.9"}, verify=not _intercepting(proxy))
        return r.status_code, r.text or ""
    import httpx

    with httpx.Client(proxy=proxy, timeout=timeout, follow_redirects=True, verify=not _intercepting(proxy),
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
_DISPLAY = ":77"
_XVFB: subprocess.Popen | None = None


def ensure_display() -> str:
    """A virtual X display for headed Chromium (Xvfb on :99, installed with apt if missing). '' when unavailable."""
    with _DISPLAY_LOCK:
        if sys.platform != "linux":  # macOS / Windows: browsers open real windows, no X server needed
            return "native"
        global _XVFB
        if _XVFB is not None and _XVFB.poll() is None:
            return _DISPLAY
        if os.environ.get("DISPLAY") and _XVFB is None:
            return os.environ["DISPLAY"]
        if not shutil.which("Xvfb"):
            subprocess.run(["apt-get", "install", "-y", "-q", "xvfb"], capture_output=True, timeout=300)
        if not shutil.which("Xvfb"):
            return ""
        # Own display number: Camoufox's headless="virtual" starts (and stops) its own Xvfb, which took :99 down
        # under the other headed browsers.
        _XVFB = subprocess.Popen(["Xvfb", _DISPLAY, "-screen", "0", "1366x900x24", "-nolisten", "tcp"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1.5)
        os.environ["DISPLAY"] = _DISPLAY
        return _DISPLAY


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
            ctx = browser.new_context(**opts, ignore_https_errors=_intercepting(proxy))
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
        cmds = {"patchright": [[sys.executable, "-m", "patchright", "install", "chromium"]],
                # Camoufox is Firefox: its system libraries (GTK etc.) are not on a server that only ran Chromium.
                "camoufox": [[sys.executable, "-m", "playwright", "install-deps", "firefox"],
                             [sys.executable, "-m", "camoufox", "fetch"]]}[name]
        try:
            for cmd in cmds:
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
            ctx = browser.new_context(locale="en-US", timezone_id="America/New_York", no_viewport=True,
                                      ignore_https_errors=_intercepting(proxy))
            return _load(ctx.new_page(), url, wait_s)
        finally:
            browser.close()


def camoufox_fetch(url: str, proxy: str | None, *, wait_s: float = 30.0) -> tuple[int, str]:
    """Camoufox: Firefox with fingerprints spoofed at the C++ level, on its own virtual display; locale and timezone
    follow the proxy's exit IP (geoip)."""
    from camoufox.sync_api import Camoufox

    with Camoufox(headless="virtual" if sys.platform == "linux" else False, proxy=_proxy_settings(proxy), geoip=bool(proxy), block_images=True,
                  humanize=True, os=["windows", "macos"]) as browser:
        return _load(browser.new_page(), url, wait_s)


def is_clean(status: int, html: str) -> bool:
    """The real page, not a bot challenge or error."""
    return status == 200 and not _summary(status, html, time.time())["challenge"]


def fetch_with_retries(url: str, proxy: str | None, *, attempts: int = 3, timeout: float = 90.0) -> tuple[int, str]:
    """Chrome-fingerprint fetch, retried (a rotating or unblocking proxy picks another route each time). Measured on
    the Apify Unblocker, Oct 2026: G2 200 first try in 23-40 s; Capterra timed out twice at 30-45 s, then 200."""
    last: tuple[int, str] = (0, "")
    for _ in range(attempts):
        try:
            last = fetch(url, proxy, impersonate="chrome", timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - next attempt
            last = (0, re.sub(r"//[^@\s/]+@", "//<redacted>@", repr(exc))[:300])
            continue
        if is_clean(*last):
            return last
    return last


def exit_country(proxy: str) -> dict[str, Any]:
    """Country and network of the proxy's current exit IP (ipinfo.io), to check country targeting."""
    try:
        from curl_cffi import requests as creq

        d = creq.get("https://ipinfo.io/json", proxies={"http": proxy, "https": proxy}, timeout=20).json()
        return {"country": d.get("country"), "org": d.get("org")}
    except Exception as exc:  # noqa: BLE001
        return {"error": re.sub(r"//[^@\s/]+@", "//<redacted>@", repr(exc))[:120]}


def rotation(url: str, proxy: str, attempts: int = 8) -> dict[str, Any]:
    """Chrome-fingerprint fetch repeated through a rotating proxy (a new exit IP per request): how many attempts get
    the real page. Cloudflare judges IPs, so one blocked attempt says little."""
    results = []
    for _ in range(attempts):
        t = time.time()
        try:
            r = _summary(*fetch(url, proxy, impersonate="chrome", timeout=30), t)
        except Exception as exc:  # noqa: BLE001
            r = {"error": re.sub(r"//[^@\s/]+@", "//<redacted>@", repr(exc))[:120]}
        results.append(r)
        if r.get("status") == 200 and not r.get("challenge"):
            break
    passed = [i for i, r in enumerate(results) if r.get("status") == 200 and not r.get("challenge")]
    return {"attempts": len(results), "passed_on_attempt": passed[0] + 1 if passed else None,
            "statuses": [r.get("status") or r.get("error") for r in results]}


def probe(url: str, proxy: str | None, *, browsers: bool = True) -> dict[str, Any]:
    """What each fetch method gets for one review URL, with and without the proxy."""
    if not allowed(url):
        raise ValueError(f"only https review pages on {', '.join(ALLOWED_HOSTS)}")
    out: dict[str, Any] = {"url": url, "proxy": bool(proxy)}
    if proxy:
        out["proxy_exit"] = exit_country(proxy)
        out["chrome_fingerprint_rotating_ips"] = rotation(url, proxy)
    tries = [("chrome_fingerprint_via_proxy", proxy, "chrome"), ("plain_via_proxy", proxy, None)] if proxy else []
    tries.append(("chrome_fingerprint_direct", None, "chrome"))
    if not browsers:
        tries = [t for t in tries if t[1]]  # proxy-only, no browsers: the quick check for a new proxy
        setup: dict[str, Any] = {"ok": False, "how": "browsers skipped"}
    else:
        setup = ensure_browser()
    out["browser_setup"] = setup
    via = "via_proxy" if proxy else "direct"
    stealth = []
    for tool in ("patchright", "camoufox") if browsers else ():
        out[f"{tool}_setup"] = ensure_tool(tool)
        if out[f"{tool}_setup"]["ok"]:
            stealth.append((f"{tool}_{via}", proxy, tool))
    if setup.get("ok"):
        stealth += [(f"headed_chromium_{via}", proxy, "headed"), (f"headless_chromium_{via}", proxy, "browser")]
    tries[:0] = stealth

    def run(imp: str, px: str | None) -> tuple[int, str]:
        if imp in ("browser", "headed"):
            return browser_fetch(url, px, headed=imp == "headed")
        if imp == "patchright":
            return patchright_fetch(url, px)
        if imp == "camoufox":
            return camoufox_fetch(url, px)
        return fetch(url, px, impersonate=imp)

    for name, px, imp in tries:
        t = time.time()
        box: dict[str, Any] = {}

        def work(imp=imp, px=px, box=box):
            try:
                box["r"] = run(imp, px)
            except Exception as exc:  # noqa: BLE001 - reported, not raised
                box["e"] = exc
        # Each method in its own thread: a browser that fails to start can leave an event loop behind, which made
        # every Playwright call after it fail ("Sync API inside the asyncio loop").
        th = threading.Thread(target=work, daemon=True)
        th.start()
        th.join(240)
        if "r" in box:
            out[name] = _summary(*box["r"], t)
        else:
            msg = re.sub(r"//[^@\s/]+@", "//<redacted>@", repr(box.get("e", "timed out after 240 s")))
            out[name] = {"error": msg[:900], "ms": int((time.time() - t) * 1000)}
    return out
