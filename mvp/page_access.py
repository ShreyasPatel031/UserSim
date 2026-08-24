"""Page access for MVP — plain HTTP fetch, then local headless Chromium; fail if still blocked."""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from capability import USER_AGENT, VIEWPORT
from capability.site_preflight import classify_page_block


class SiteAccessBlockedError(RuntimeError):
    def __init__(self, reason: str, *, session_url: str | None = None) -> None:
        self.reason = reason
        self.session_url = session_url
        msg = f"Site blocked or unreachable: {reason}"
        if session_url:
            msg += f" (Browserbase session: {session_url})"
        super().__init__(msg)


@dataclass(frozen=True)
class PageAccessResult:
    text: str
    final_url: str
    title: str
    backend: str
    session_url: str | None = None


_BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _strip_html(html: str, max_chars: int = 12_000) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


async def _playwright_body(
    *,
    connect_url: str | None,
    url: str,
    timeout_ms: int = 35000,
) -> tuple[str, str, str, bool, str]:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        if connect_url:
            browser = await p.chromium.connect_over_cdp(connect_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context(
                viewport=VIEWPORT, user_agent=USER_AGENT
            )
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport=VIEWPORT, user_agent=USER_AGENT)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(1500)
        except Exception as exc:  # noqa: BLE001
            await browser.close()
            return "", url, "", True, f"navigation_error:{exc}"[:200]

        try:
            title = await page.title()
        except Exception:  # noqa: BLE001
            title = ""
        final_url = page.url
        try:
            body = (await page.inner_text("body"))[:12_000]
        except Exception:  # noqa: BLE001
            body = ""
        await browser.close()

    blocked, reason = classify_page_block(final_url=final_url, title=title, body=body)
    if not blocked and len(body.strip()) < 80:
        blocked, reason = True, "blocked_body:empty_or_js_shell"
    return body, final_url, title, blocked, reason


async def _try_httpx(url: str) -> tuple[str, str, str, bool, str]:
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=_BROWSER_HEADERS)
        if resp.status_code >= 400:
            return "", url, "", True, f"http_{resp.status_code}"
        stripped = _strip_html(resp.text)
        title_match = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.I | re.S)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
        blocked, reason = classify_page_block(
            final_url=str(resp.url), title=title, body=stripped
        )
        if not blocked and len(stripped) < 120:
            blocked, reason = True, "blocked_body:empty_or_js_shell"
        return stripped, str(resp.url), title, blocked, reason
    except httpx.HTTPError as exc:
        return "", url, "", True, f"http_error:{exc}"[:200]


async def fetch_page_access(url: str) -> PageAccessResult:
    """Try a plain HTTP fetch, then a local headless Chromium. Raise if both are blocked."""
    body, final_url, title, blocked, reason = await _try_httpx(url)
    if not blocked and body:
        return PageAccessResult(text=body, final_url=final_url, title=title, backend="http")

    body, final_url, title, blocked, reason = await _playwright_body(connect_url=None, url=url)
    if blocked or not body:
        raise SiteAccessBlockedError(reason)
    return PageAccessResult(text=body, final_url=final_url, title=title, backend="local_playwright")
