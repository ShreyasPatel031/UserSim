"""Fetch one visitor-supplied page (plus at most one obvious sub-page) with SSRF protection.

- http/https only, default ports only (80/443), no credentials in the URL, no IP-literal hosts.
- The hostname is resolved once; every address must be globally routable (IPv4-mapped, NAT64, 6to4 and Teredo
  addresses are unwrapped and checked too). The connection then goes to that validated address (Host header and TLS
  SNI/certificate check use the hostname), so a second DNS answer cannot redirect it (no DNS rebinding).
  Re-checked on every redirect hop (max 3 hops).
- Accept-Encoding: identity; raw bytes capped at 1.5 MB (compressed bodies are inflated with the same cap);
  8 s per request and 12 s overall; text/html or text/plain only.
- Product Hunt hosts are refused (no PH scraping from the public tool).
"""
from __future__ import annotations

import asyncio
import codecs
import html
import ipaddress
import re
import socket
import zlib
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 1_500_000
TIMEOUT_S = 8.0
DEADLINE_S = 12.0
MAX_HOPS = 3
UA = "Mozilla/5.0 (compatible; AtelierSim/1.0; +https://atelier-sim.com/try)"
BLOCKED_HOSTS = ("producthunt.com", "metadata.google.internal", "localhost")
NAT64 = ipaddress.ip_network("64:ff9b::/96")


class FetchError(Exception):
    pass


def _ip_ok(ip: str) -> bool:
    a = ipaddress.ip_address(ip.split("%")[0])
    inner = []
    if a.version == 6:
        if a.ipv4_mapped:
            inner.append(a.ipv4_mapped)
        if a.sixtofour:
            inner.append(a.sixtofour)
        if a.teredo:
            inner.extend(a.teredo)
        if a in NAT64:
            inner.append(ipaddress.IPv4Address(int(a) & 0xFFFFFFFF))
        if inner:   # tunnelled/translated forms: judge by the address they reach
            return all(_ip_ok(str(x)) for x in inner)
    return a.is_global and not a.is_multicast


async def _resolve(host: str) -> list[str]:
    try:
        infos = await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo, host, None, 0, socket.SOCK_STREAM), timeout=4)
    except Exception as exc:  # noqa: BLE001
        raise FetchError("Could not resolve that domain.") from exc
    addrs = sorted({i[4][0] for i in infos})
    if not addrs or not all(_ip_ok(x) for x in addrs):
        raise FetchError("That address points to a private or internal network.")
    return addrs


def _normalize(url: str) -> str:
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url


def _static_checks(url: str):
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise FetchError("Only http(s) links are allowed.")
    if parts.username or parts.password:
        raise FetchError("Links with credentials are not allowed.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or "." not in host:
        raise FetchError("That does not look like a public web address.")
    try:
        port = parts.port
    except ValueError as exc:
        raise FetchError("That port is not allowed.") from exc
    if port not in (None, 80, 443):
        raise FetchError("Only standard web ports are allowed.")
    if any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS):
        raise FetchError("Product Hunt pages and internal hosts can't be fetched here; paste the product's own site.")
    try:
        ipaddress.ip_address(host.strip("[]"))
        raise FetchError("Use a domain name, not an IP address.")
    except ValueError:
        pass
    return parts, host


async def check_url(url: str) -> str:
    url = _normalize(url)
    parts, host = _static_checks(url)
    await _resolve(host)
    return parts._replace(fragment="").geturl()


def _decode(raw: bytes, ctype: str, encoding_hdr: str) -> str:
    enc = (encoding_hdr or "").lower().strip()
    if enc in ("gzip", "deflate", "x-gzip"):
        d = zlib.decompressobj(16 + zlib.MAX_WBITS if "gzip" in enc else zlib.MAX_WBITS)
        raw = d.decompress(raw, MAX_BYTES)
    elif enc not in ("", "identity"):
        raise FetchError("The site sent an encoding we don't read.")
    m = re.search(r"charset=([\w\-]+)", ctype or "", re.I)
    charset = m.group(1) if m else "utf-8"
    try:
        codecs.lookup(charset)
    except LookupError:
        charset = "utf-8"
    return raw.decode(charset, errors="replace")


def _behind_proxy() -> bool:
    """Local dev sandboxes reach the internet only through an HTTPS proxy that connects by hostname; there the proxy
    does the resolution. Production (Vercel) has no proxy, so connections are pinned to the validated IP."""
    import os
    if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
        return False
    return bool(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))


async def _get_pinned(url: str) -> tuple[int, dict, bytes]:
    """GET `url` connecting to a validated IP of its host; TLS still verifies the hostname."""
    parts, host = _static_checks(url)
    ip = (await _resolve(host))[0]
    if _behind_proxy():
        return await _get_via(url, {"User-Agent": UA, "Accept": "text/html,text/plain;q=0.9",
                                    "Accept-Encoding": "identity"}, None, trust_env=True)
    netloc_ip = f"[{ip}]" if ":" in ip else ip
    if parts.port:
        netloc_ip += f":{parts.port}"
    target = parts._replace(netloc=netloc_ip, fragment="").geturl()
    headers = {"User-Agent": UA, "Accept": "text/html,text/plain;q=0.9", "Accept-Encoding": "identity",
               "Host": host + (f":{parts.port}" if parts.port else "")}
    return await _get_via(target, headers, {"sni_hostname": host}, trust_env=False)


async def _get_via(target: str, headers: dict, ext: dict | None, trust_env: bool) -> tuple[int, dict, bytes]:
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False, trust_env=trust_env) as client:
        req = client.build_request("GET", target, headers=headers, extensions=ext or {})
        r = await client.send(req, stream=True)
        try:
            buf = bytearray()
            if r.status_code < 300:
                async for chunk in r.aiter_raw():
                    buf.extend(chunk)
                    if len(buf) > MAX_BYTES:
                        break
            return r.status_code, dict(r.headers), bytes(buf[:MAX_BYTES])
        finally:
            await r.aclose()


async def _fetch(url: str) -> dict:
    cur = await check_url(url)
    for _ in range(MAX_HOPS + 1):
        status, hdrs, raw = await _get_pinned(cur)
        h = {k.lower(): v for k, v in hdrs.items()}
        if status in (301, 302, 303, 307, 308) and h.get("location"):
            cur = await check_url(urljoin(cur, h["location"]))
            continue
        if status >= 400:
            raise FetchError(f"The site answered HTTP {status}.")
        ctype = h.get("content-type", "")
        if ctype and not any(t in ctype for t in ("text/html", "text/plain", "application/xhtml")):
            raise FetchError("That link is not a web page.")
        return {"url": url, "final_url": cur, "status": status,
                "html": _decode(raw, ctype, h.get("content-encoding", ""))}
    raise FetchError("Too many redirects.")


async def fetch(url: str) -> dict:
    try:
        return await asyncio.wait_for(_fetch(url), timeout=DEADLINE_S)
    except asyncio.TimeoutError as exc:
        raise FetchError("The site took too long to answer.") from exc
    except httpx.HTTPError as exc:
        raise FetchError("Could not load that page.") from exc


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
