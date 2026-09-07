#!/usr/bin/env python3
"""Exercise the captcha stack against Google's public reCAPTCHA demo.

Usage:
  MVP_CAPTCHA_OSS=1 PYTHONPATH=src:. .venv/bin/python scripts/local/test_captcha_demo.py
  USE_BROWSERBASE=1 MVP_CAPTCHA_SOLVER=1 ...  # also try Browserbase native solver
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

DEMO_URL = "https://www.google.com/recaptcha/api2/demo"


async def _run(url: str, *, headed: bool, use_bb: bool) -> dict:
    from playwright.async_api import async_playwright

    from mvp.captcha import page_looks_captcha_blocked, solve_captcha_on_page, status

    out: dict = {"url": url, "status": status(), "steps": []}
    bb_session = None
    try:
        async with async_playwright() as p:
            if use_bb:
                from capability.browserbase_client import close_session, create_session

                bb_session = create_session(
                    proxies=True, keep_alive=False, solve_captchas=True, advanced_stealth=False
                )
                browser = await p.chromium.connect_over_cdp(bb_session.connect_url)
                out["backend"] = "browserbase"
                out["session"] = bb_session.session_url
            else:
                browser = await p.chromium.launch(headless=not headed)
                out["backend"] = "local_chrome"

            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2000)

            detect = await page_looks_captcha_blocked(page)
            out["steps"].append({"detect_before": detect})

            # Click the visible checkbox iframe so a challenge / BB solver can engage.
            try:
                frame = page.frame_locator('iframe[src*="recaptcha/api2/anchor"]').first
                box = frame.locator("#recaptcha-anchor").first
                await box.click(timeout=8000)
                out["steps"].append({"clicked_checkbox": True})
                await page.wait_for_timeout(4000)
            except Exception as exc:
                out["steps"].append({"clicked_checkbox": False, "error": str(exc)[:160]})

            detect2 = await page_looks_captcha_blocked(page)
            out["steps"].append({"detect_after_click": detect2})

            # Force the full solver stack even if the checkbox alone scored green.
            result = await solve_captcha_on_page(page)
            out["solve"] = result

            # If still not verified, explicitly try the OSS image solver once more.
            try:
                from mvp.captcha import _try_oss_image_solver

                oss = await _try_oss_image_solver(page)
                if oss:
                    out["steps"].append({"oss_retry": oss})
                    if oss.get("ok") and not result.get("ok"):
                        result = oss
                        out["solve"] = result
            except Exception as exc:
                out["steps"].append({"oss_retry_error": str(exc)[:160]})

            out["detect_final"] = await page_looks_captcha_blocked(page)

            # Check Google's checkbox aria-checked / response textarea.
            try:
                token_len = await page.evaluate(
                    """() => {
                      const t = document.querySelector('#g-recaptcha-response, textarea[name="g-recaptcha-response"]');
                      return t && t.value ? t.value.length : 0;
                    }"""
                )
                out["token_len"] = token_len
            except Exception:
                out["token_len"] = None

            # Demo page has a Submit button that only works with a valid token.
            try:
                await page.locator("#recaptcha-demo-submit, button[type=submit]").first.click(
                    timeout=5000
                )
                await page.wait_for_timeout(2000)
                body = (await page.inner_text("body"))[:500].lower()
                out["submit_ok"] = "success" in body or "verified" in body or "thank" in body
                out["body_snip"] = body[:200]
            except Exception as exc:
                out["submit_ok"] = False
                out["submit_error"] = str(exc)[:160]

            if not use_bb:
                await browser.close()
    finally:
        if bb_session is not None:
            try:
                from capability.browserbase_client import close_session

                close_session(bb_session.id)
            except Exception:
                pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEMO_URL)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument(
        "--browserbase",
        action="store_true",
        help="Use Browserbase (respects USE_BROWSERBASE / secrets)",
    )
    args = ap.parse_args()
    use_bb = args.browserbase or os.environ.get("USE_BROWSERBASE", "").lower() in {
        "1",
        "true",
        "yes",
    }
    # Unattended local runs should not hang on human ntfy.
    os.environ.setdefault("MVP_CAPTCHA_ALLOW_HUMAN", "0")
    os.environ.setdefault("SIGNUP_HEADLESS", "0" if args.headed else "1")
    os.environ.setdefault("MVP_CAPTCHA_OSS", "1")

    result = asyncio.run(_run(args.url, headed=args.headed, use_bb=use_bb))
    print(json.dumps(result, indent=2))
    ok = bool(result.get("solve", {}).get("ok") or result.get("submit_ok"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
