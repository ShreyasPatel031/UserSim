"""Loop 16: reCAPTCHA v3 token refresh, v3 action capture, paid solve after a visible captcha rejection (FeedBear).

FeedBear (reCAPTCHA v3) is meant to mint its token once on page load from an inline script; that script is blocked by
the page's own CSP, so the hidden g-recaptcha-response field stays empty (or a token would expire after 2 minutes)
and Register says "reCAPTCHA verification failed".
"""
from __future__ import annotations

import asyncio
import os
import shutil

import pytest

from mvp.sim_mcp.server import _CAPTCHA_FAILED_RE, _RECAPTCHA_KIND_JS, _V3_ACTION_JS, _V3_REFRESH_JS
from mvp.sim_mcp.sessions import V3_ACTION_HOOK

API = "https://www.google.com/recaptcha/api.js?render=6LabcdefghijklmnopqrstuvwxyzABCDEFGHIJKL"


def test_captcha_failed_wording():
    assert _CAPTCHA_FAILED_RE.search("reCAPTCHA verification failed. Please try again.")
    assert _CAPTCHA_FAILED_RE.search("Captcha expired")
    assert not _CAPTCHA_FAILED_RE.search("This site is protected by reCAPTCHA and the Google Privacy Policy")


def _chrome() -> str | None:
    return os.environ.get("USERSIM_TEST_CHROME") or shutil.which("google-chrome") or shutil.which("chromium")


STUB = ("window.grecaptcha={ready:function(f){f()},execute:function(k,o){window.__k=k;window.__a=o&&o.action;"
        "return Promise.resolve('T'.repeat(40))}};")


async def _page_eval(body: str, js: str, arg=None, hook: bool = False):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        kw = {"executable_path": _chrome()} if _chrome() else {}
        try:
            b = await p.chromium.launch(headless=True, **kw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"no browser: {exc!r}")
        ctx = await b.new_context()
        if hook:
            await ctx.add_init_script(V3_ACTION_HOOK)
        page = await ctx.new_page()

        async def route(r):
            if r.request.url.startswith("https://site.test/"):
                await r.fulfill(status=200, content_type="text/html", body=body)
            elif "recaptcha/api.js" in r.request.url:
                await r.fulfill(status=200, content_type="application/javascript", body="")
            else:
                await r.abort()

        await page.route("**/*", route)
        await page.goto("https://site.test/")
        await page.wait_for_timeout(300)
        out = await (page.evaluate(js, arg) if arg is not None else page.evaluate(js))
        extra = await page.evaluate("() => ({k: window.__k || null, a: window.__a || null, "
                                    "v: (document.querySelector('[name=g-recaptcha-response]') || {}).value || ''})")
        await b.close()
        return out, extra


def test_probe_sees_injected_v3_api_js():
    pytest.importorskip("playwright.async_api")
    body = f"<script>const s=document.createElement('script');s.src='{API}';document.head.appendChild(s);</script>"
    out, _ = asyncio.run(_page_eval(body, _RECAPTCHA_KIND_JS))
    assert out["v3"] is True


def test_v3_refresh_fills_empty_field():
    pytest.importorskip("playwright.async_api")
    body = f"<script src='{API}'></script><script>{STUB}</script><input type=hidden name=g-recaptcha-response value=''>"
    out, extra = asyncio.run(_page_eval(body, _V3_REFRESH_JS, "submit"))
    assert out["refreshed"] is True and extra["a"] == "submit" and len(extra["v"]) == 40
    assert extra["k"] == "6LabcdefghijklmnopqrstuvwxyzABCDEFGHIJKL"


def test_v3_refresh_skips_v2_pages():
    pytest.importorskip("playwright.async_api")
    body = ("<script src='https://www.google.com/recaptcha/api.js?render=explicit'></script>"
            f"<script>{STUB}</script><input type=hidden name=g-recaptcha-response>")
    out, extra = asyncio.run(_page_eval(body, _V3_REFRESH_JS, "submit"))
    assert out["refreshed"] is False and extra["v"] == ""


def test_hook_records_site_action():
    pytest.importorskip("playwright.async_api")
    body = ("<script>window.grecaptcha={ready:function(f){setTimeout(f,10)}};"
            "setTimeout(function(){window.grecaptcha.execute=function(k,o){return Promise.resolve('x')};},0);"
            "grecaptcha.ready(function(){grecaptcha.execute('K',{action:'signup_form'})});</script>")
    out, _ = asyncio.run(_page_eval(body, _V3_ACTION_JS, hook=True))
    assert out == "signup_form"
