"""In-house fetching of G2 / Capterra / Product Hunt review pages (to replace Apify), through a residential proxy.

Product Hunt (Cloudflare) and G2 (DataDome) block data-centre IPs outright, so pages go through PROXY_URL (a rotating
residential proxy, e.g. DataImpulse) when it is set. curl_cffi sends Chrome's TLS/HTTP2 fingerprint, which plain
HTTP clients do not; no browser is needed when the protection lets that through.

probe() reports, for one review URL, what each way of fetching gets back (status, title, size, whether a bot
challenge was served), so the approach can be measured on the real sites before parsers are built on it.
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse

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


def probe(url: str, proxy: str | None) -> dict[str, Any]:
    """What each fetch method gets for one review URL, with and without the proxy."""
    if not allowed(url):
        raise ValueError(f"only https review pages on {', '.join(ALLOWED_HOSTS)}")
    out: dict[str, Any] = {"url": url, "proxy": bool(proxy)}
    tries = [("chrome_fingerprint_via_proxy", proxy, "chrome"), ("plain_via_proxy", proxy, None)] if proxy else []
    tries.append(("chrome_fingerprint_direct", None, "chrome"))
    for name, px, imp in tries:
        t = time.time()
        try:
            status, html = fetch(url, px, impersonate=imp)
            out[name] = _summary(status, html, t)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            msg = re.sub(r"//[^@\s/]+@", "//<redacted>@", repr(exc))  # proxy errors can echo user:pass
            out[name] = {"error": msg[:300], "ms": int((time.time() - t) * 1000)}
    return out
