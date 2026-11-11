"""Fetch one visitor-supplied page (plus at most one obvious sub-page) with SSRF protection.

- http/https only, default ports only (80/443), no credentials in the URL.
- Hostname resolved first; every address must be public (no private, loopback, link-local, multicast, reserved,
  CGNAT or cloud metadata). Re-checked on every redirect hop (max 3 hops).
- 8 s timeout per request, 1.5 MB body cap, text/html or text/plain only.
- Product Hunt hosts are refused (no PH scraping from the public tool).
"""
from __future__ import annotations

import asyncio
import html
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 1_500_000
TIMEOUT_S = 8.0
MAX_HOPS = 3
UA = "Mozilla/5.0 (compatible; AtelierSim/1.0; +https://atelier-sim.com/try)"
BLOCKED_HOSTS = ("producthunt.com", "metadata.google.internal", "localhost")


class FetchError(Exception):
    pass


def _ip_ok(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved
                or a.is_unspecified or (a.version == 4 and a in ipaddress.ip_network("100.64.0.0/10")))


async def check_url(url: str) -> str:
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise FetchError("Only http(s) links are allowed.")
    if parts.username or parts.password:
        raise FetchError("Links with credentials are not allowed.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or "." not in host:
        raise FetchError("That does not look like a public web address.")
    if parts.port not in (None, 80, 443):
        raise FetchError("Only standard web ports are allowed.")
    if any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS):
        raise FetchError("Product Hunt pages and internal hosts can't be fetched here; paste the product's own site.")
    try:
        ipaddress.ip_address(host)
        raise FetchError("Use a domain name, not an IP address.")
    except ValueError:
        pass
    try:
        infos = await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo, host, None), timeout=4)
    except Exception as exc:  # noqa: BLE001
        raise FetchError("Could not resolve that domain.") from exc
    addrs = {i[4][0] for i in infos}
    if not addrs or not all(_ip_ok(a) for a in addrs):
        raise FetchError("That address points to a private or internal network.")
    return parts._replace(fragment="").geturl()


async def fetch(url: str) -> dict:
    """-> {url, final_url, status, html (str, capped)}"""
    cur = await check_url(url)
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False,
                                 headers={"User-Agent": UA, "Accept": "text/html,text/plain;q=0.9"}) as client:
        for _ in range(MAX_HOPS + 1):
            async with client.stream("GET", cur) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    cur = await check_url(urljoin(cur, r.headers["location"]))
                    continue
                ctype = r.headers.get("content-type", "")
                if r.status_code >= 400:
                    raise FetchError(f"The site answered HTTP {r.status_code}.")
                if ctype and not any(t in ctype for t in ("text/html", "text/plain", "application/xhtml")):
                    raise FetchError("That link is not a web page.")
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > MAX_BYTES:
                        break
                enc = r.encoding or "utf-8"
                return {"url": url, "final_url": cur, "status": r.status_code,
                        "html": bytes(buf[:MAX_BYTES]).decode(enc, errors="replace")}
    raise FetchError("Too many redirects.")


def extract(page_html: str) -> dict:
    """Title, meta description and visible text (scripts/styles removed)."""
    h = page_html or ""
    title = re.search(r"<title[^>]*>(.*?)</title>", h, re.S | re.I)
    desc = re.search(r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]*content=["\']([^"\']*)', h, re.I)
    body = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", h)
    body = re.sub(r"(?s)<!--.*?-->", " ", body)
    body = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|section|tr)>", "\n", body)
    text = html.unescape(re.sub(r"<[^>]+>", " ", body))
    text = "\n".join(" ".join(l.split()) for l in text.splitlines())
    text = re.sub(r"\n{2,}", "\n", text).strip()
    links = re.findall(r'href=["\']([^"\'#]+)["\']', h, re.I)
    return {"title": html.unescape(title.group(1).strip())[:200] if title else "",
            "description": html.unescape(desc.group(1).strip())[:400] if desc else "",
            "text": text[:20000], "links": links[:400]}


def pricing_link(base: str, links: list[str]) -> str | None:
    host = urlsplit(base).hostname
    for l in links:
        u = urljoin(base, l)
        p = urlsplit(u)
        if p.hostname == host and re.search(r"/(pricing|plans)/?$", p.path, re.I):
            return u
    return None


async def fetch_product(url: str) -> dict:
    page = await fetch(url)
    ex = extract(page["html"])
    out = {"url": page["final_url"], **{k: ex[k] for k in ("title", "description", "text")}, "pricing_text": ""}
    pl = pricing_link(page["final_url"], ex["links"])
    if pl:
        try:
            pp = await fetch(pl)
            out["pricing_text"] = extract(pp["html"])["text"][:4000]
        except Exception:  # noqa: BLE001 - optional sub-page
            pass
    return out
