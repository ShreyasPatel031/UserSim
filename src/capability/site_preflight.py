"""Detect WAF/CAPTCHA blocks before spending agent tokens."""

from __future__ import annotations

import re
from dataclasses import dataclass

from capability import USER_AGENT, VIEWPORT

# Confirmed Akamai/WAF blocks from datacenter IP (see mini2_tasks.py, HOW_TO_RUN_OM2W.md).
KNOWN_BLOCKED_WEBSITES: frozenset[str] = frozenset({"uniqlo", "apartments"})

_TITLE_BLOCK_RE = re.compile(
    r"access denied|403 forbidden|just a moment|attention required|verify you are human|"
    r"robot check|pardon our interruption|security check|request blocked",
    re.I,
)
_BODY_BLOCK_RE = re.compile(
    r"access denied|akamai|you don't have permission|verify you are a human|"
    r"unusual traffic|automated access|bot detection|cf-browser-verification|"
    r"please enable cookies|checking your browser|errors\.edgesuite\.net",
    re.I,
)
_URL_BLOCK_RE = re.compile(r"/sorry/|captcha|challenge|recaptcha", re.I)


@dataclass(frozen=True)
class PreflightResult:
    blocked: bool
    reason: str
    final_url: str
    title: str
    screenshot: bytes | None


def classify_page_block(*, final_url: str, title: str, body: str) -> tuple[bool, str]:
    if _URL_BLOCK_RE.search(final_url):
        return True, f"blocked_url:{final_url}"
    if _TITLE_BLOCK_RE.search(title):
        return True, f"blocked_title:{title[:120]}"
    if _BODY_BLOCK_RE.search(body):
        return True, "blocked_body:waf_or_captcha"
    return False, "ok"


async def preflight_start_url(start_url: str, *, timeout_ms: int = 25000) -> PreflightResult:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport=VIEWPORT, user_agent=USER_AGENT)
        try:
            await page.goto(start_url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(800)
        except Exception as exc:  # noqa: BLE001
            await browser.close()
            return PreflightResult(
                blocked=True,
                reason=f"navigation_error:{exc}"[:200],
                final_url=start_url,
                title="",
                screenshot=None,
            )
        try:
            title = await page.title()
        except Exception:  # noqa: BLE001
            title = ""
        final_url = page.url
        screenshot = await page.screenshot(type="png")
        try:
            body = (await page.inner_text("body"))[:4000]
        except Exception:  # noqa: BLE001
            body = ""
        await browser.close()

    blocked, reason = classify_page_block(final_url=final_url, title=title, body=body)
    return PreflightResult(blocked, reason, final_url, title, screenshot)


async def preflight_start_url_browserbase(
    start_url: str,
    *,
    connect_url: str,
    timeout_ms: int = 30000,
) -> PreflightResult:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(connect_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context(
            viewport=VIEWPORT, user_agent=USER_AGENT
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(start_url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(800)
        except Exception as exc:  # noqa: BLE001
            await browser.close()
            return PreflightResult(
                blocked=True,
                reason=f"navigation_error:{exc}"[:200],
                final_url=start_url,
                title="",
                screenshot=None,
            )
        try:
            title = await page.title()
        except Exception:  # noqa: BLE001
            title = ""
        final_url = page.url
        screenshot = await page.screenshot(type="png")
        try:
            body = (await page.inner_text("body"))[:4000]
        except Exception:  # noqa: BLE001
            body = ""
        await browser.close()

    blocked, reason = classify_page_block(final_url=final_url, title=title, body=body)
    return PreflightResult(blocked, reason, final_url, title, screenshot)
