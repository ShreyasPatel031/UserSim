"""Smoke-test blocked OM2W sites via local Chromium vs Browserbase."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capability import OUT_DIR, USER_AGENT, VIEWPORT
from capability.browserbase_client import BrowserbaseConfigError, close_session, create_session
from capability.site_preflight import PreflightResult, classify_page_block, preflight_start_url


DEFAULT_SITES = [
    ("example.com", "https://example.com/"),
    ("uniqlo", "https://www.uniqlo.com/us/en/"),
    ("apartments", "https://www.apartments.com/"),
]


@dataclass(frozen=True)
class SiteProbe:
    site: str
    url: str
    backend: str
    blocked: bool
    reason: str
    title: str
    final_url: str
    session_url: str | None = None


async def _probe_browserbase(url: str, *, proxies: bool) -> tuple[PreflightResult, str | None]:
    session = create_session(proxies=proxies)
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(session.connect_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context(
                viewport=VIEWPORT, user_agent=USER_AGENT
            )
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(800)
            except Exception as exc:  # noqa: BLE001
                return (
                    PreflightResult(
                        blocked=True,
                        reason=f"navigation_error:{exc}"[:200],
                        final_url=url,
                        title="",
                        screenshot=None,
                    ),
                    session.session_url,
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
        return (
            PreflightResult(blocked=blocked, reason=reason, final_url=final_url, title=title, screenshot=screenshot),
            session.session_url,
        )
    finally:
        close_session(session.id)


async def _probe_local(url: str) -> PreflightResult:
    return await preflight_start_url(url)


async def _run_probes(sites: list[tuple[str, str]], *, proxies: bool) -> list[SiteProbe]:
    out: list[SiteProbe] = []
    for site, url in sites:
        local = await _probe_local(url)
        out.append(
            SiteProbe(
                site=site,
                url=url,
                backend="local",
                blocked=local.blocked,
                reason=local.reason,
                title=local.title,
                final_url=local.final_url,
            )
        )
        try:
            bb, session_url = await _probe_browserbase(url, proxies=proxies)
        except Exception as exc:  # noqa: BLE001
            out.append(
                SiteProbe(
                    site=site,
                    url=url,
                    backend=f"browserbase{'+proxies' if proxies else ''}",
                    blocked=True,
                    reason=f"browserbase_error:{exc}"[:200],
                    title="",
                    final_url=url,
                    session_url=None,
                )
            )
            continue
        out.append(
            SiteProbe(
                site=site,
                url=url,
                backend=f"browserbase{'+proxies' if proxies else ''}",
                blocked=bb.blocked,
                reason=bb.reason,
                title=bb.title,
                final_url=bb.final_url,
                session_url=session_url,
            )
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare local vs Browserbase on blocked sites")
    ap.add_argument("--proxies", action="store_true", help="Enable Browserbase residential proxies (paid)")
    ap.add_argument("--site", action="append", default=[], help="site_key=url (default: example, uniqlo, apartments)")
    ap.add_argument("--out", type=Path, default=OUT_DIR / "browserbase_block_smoke.json")
    args = ap.parse_args()

    sites = DEFAULT_SITES
    if args.site:
        sites = []
        for item in args.site:
            if "=" not in item:
                raise SystemExit("--site expects key=url")
            k, u = item.split("=", 1)
            sites.append((k.strip(), u.strip()))

    try:
        rows = asyncio.run(_run_probes(sites, proxies=args.proxies))
    except BrowserbaseConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = {"proxies": args.proxies, "results": [asdict(r) for r in rows]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))

    print(f"Wrote {args.out}\n")
    print(f"{'Site':<12} {'Backend':<22} {'Blocked':<8} Title / reason")
    print("-" * 72)
    for r in rows:
        title = (r.title or r.reason)[:40]
        print(f"{r.site:<12} {r.backend:<22} {str(r.blocked):<8} {title}")
        if r.session_url:
            print(f"             session: {r.session_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
