"""Loop 15: paid-solver reCAPTCHA typing and token delivery; parent-company auth domain in the proof check.

1. detect_sitekey reports a plain v2 widget as 'recaptcha'; _paid_token only kept types containing 'v2', so every
   reCAPTCHA (Featurebase's invisible v2 included) was sent to CapSolver as v3 and the token was useless.
2. An explicit-render v2 widget receives its token through the render callback, not execute()'s return value.
3. Bugsnag's signup is hosted on auth.id.smartbear.com (SmartBear owns Bugsnag): opened_on_product allows that
   parent domain only when the run ends signed in on bugsnag.com itself.
"""
from __future__ import annotations

import asyncio
import os
import shutil

import pytest

from mvp.captcha import _solver_task
from mvp.sim_mcp.report import _parent_auth_opened
from mvp.sim_mcp.server import _PAID_JS, _RECAPTCHA_KIND_JS, _paid_captcha_type


def test_plain_recaptcha_is_v2_not_v3():
    assert _paid_captcha_type("recaptcha", "recaptcha", {"invisible": True}) == ("recaptcha_v2", True)
    assert _paid_captcha_type("recaptcha", "recaptcha", {}) == ("recaptcha_v2", False)


def test_render_sitekey_is_v3():
    assert _paid_captcha_type("recaptcha", "recaptcha", {"v3": True, "invisible": True}) == ("recaptcha_v3", False)
    assert _paid_captcha_type("recaptcha", "recaptcha_v3", {}) == ("recaptcha_v3", False)


def test_enterprise_and_turnstile_and_override():
    assert _paid_captcha_type("recaptcha", "recaptcha", {"enterprise": True}) == ("recaptcha_v2_enterprise", False)
    assert _paid_captcha_type("recaptcha", "", {"enterprise": True, "v3": True}) == ("recaptcha_v3_enterprise", False)
    assert _paid_captcha_type("turnstile", "turnstile", {"invisible": True}) == ("turnstile", False)
    assert _paid_captcha_type("recaptcha", "recaptcha", {}, "recaptcha_v3") == ("recaptcha_v3", False)


def test_invisible_flag_reaches_capsolver_task():
    t = _solver_task("ReCaptchaV2TaskProxyLess", sitekey="K", page_url="https://x.test/", action=None, invisible=True)
    assert t["isInvisible"] is True
    t3 = _solver_task("ReCaptchaV3TaskProxyLess", sitekey="K", page_url="https://x.test/", action="a", invisible=True)
    assert "isInvisible" not in t3 and t3["pageAction"] == "a"


def _row(opened: str, final: str, signed_in: bool, site: str = "https://app.bugsnag.com/user/new") -> dict:
    return {"site_url": site, "page_url": opened, "final_url": final,
            "page_verdict": {"signed_in_app_page": signed_in}}


def test_bugsnag_parent_auth_allowed_when_signed_in_on_product():
    assert _parent_auth_opened(_row("https://auth.id.smartbear.com/u/signup", "https://app.bugsnag.com/", True))


def test_parent_auth_strict():
    # not signed in, or ended on the parent, or an unmapped product, or a foreign auth domain: all refused
    assert not _parent_auth_opened(_row("https://auth.id.smartbear.com/u/signup", "https://app.bugsnag.com/", False))
    assert not _parent_auth_opened(_row("https://auth.id.smartbear.com/u/signup", "https://id.smartbear.com/", True))
    assert not _parent_auth_opened(_row("https://auth.id.smartbear.com/", "https://app.example.com/", True,
                                        site="https://example.com/"))
    assert not _parent_auth_opened(_row("https://accounts.evil.com/", "https://app.bugsnag.com/", True))


def _chrome() -> str | None:
    return os.environ.get("USERSIM_TEST_CHROME") or shutil.which("google-chrome") or shutil.which("chromium")


async def _eval(html: str, js: str, arg=None):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        kw = {"executable_path": _chrome()} if _chrome() else {}
        try:
            b = await p.chromium.launch(headless=True, **kw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"no browser: {exc!r}")
        page = await b.new_page()
        await page.route("**/*", lambda r: r.abort())
        await page.set_content(html)
        out = await (page.evaluate(js, arg) if arg is not None else page.evaluate(js))
        extra = await page.evaluate("() => window.__got || null")
        await b.close()
        return out, extra


def test_kind_probe_explicit_invisible_v2():
    pytest.importorskip("playwright.async_api")
    html = ('<script src="https://www.google.com/recaptcha/api.js?render=explicit"></script>'
            '<iframe src="https://www.google.com/recaptcha/api2/anchor?k=K&size=invisible"></iframe>')
    out, _ = asyncio.run(_eval(html, _RECAPTCHA_KIND_JS))
    assert out["v3"] is False and out["invisible"] is True


def test_kind_probe_v3():
    pytest.importorskip("playwright.async_api")
    html = ('<script src="https://www.google.com/recaptcha/api.js?render=6LabcdefghijklmnopqrstuvwxyzABCDEFGHIJKL"></script>'
            '<iframe src="https://www.google.com/recaptcha/api2/anchor?k=K&size=invisible"></iframe>')
    out, _ = asyncio.run(_eval(html, _RECAPTCHA_KIND_JS))
    assert out["v3"] is True


def test_paid_js_calls_v2_render_callback():
    pytest.importorskip("playwright.async_api")
    html = ("<textarea name='g-recaptcha-response'></textarea><script>"
            "window.___grecaptcha_cfg={clients:{0:{a:{b:{sitekey:'K',callback:function(t){window.__got=t;}}}}}};"
            "window.grecaptcha={execute:function(){},getResponse:function(){return ''}};</script>")
    out, got = asyncio.run(_eval(html, _PAID_JS, ["recaptcha", "TOKEN"]))
    assert out == {"callbacks": 1} and got == "TOKEN"


async def _turnstile_key() -> str:
    from playwright.async_api import async_playwright

    from mvp.sim_mcp.server import _SITEKEY_JS

    async with async_playwright() as p:
        kw = {"executable_path": _chrome()} if _chrome() else {}
        try:
            b = await p.chromium.launch(headless=True, **kw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"no browser: {exc!r}")
        page = await b.new_page()

        async def route(r):
            if "challenges.cloudflare.com" in r.request.url:
                await r.fulfill(status=200, body="<html></html>", content_type="text/html")
            elif r.request.url.startswith("https://site.test/"):
                await r.fulfill(status=200, content_type="text/html", body=(
                    "<div id=w></div><script>const f=document.createElement('iframe');"
                    "f.src='https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/f/av0/rch/x/"
                    "0x4AAAAAAAtestKeyTestKey/auto/fbE/new/normal';"
                    "document.getElementById('w').attachShadow({mode:'closed'}).appendChild(f);</script>"))
            else:
                await r.abort()

        await page.route("**/*", route)
        await page.goto("https://site.test/")
        await page.wait_for_timeout(500)
        key = await page.evaluate(_SITEKEY_JS, "turnstile")
        await b.close()
        return key


def test_turnstile_sitekey_from_resource_timing():
    # Loop 15 Typefully: explicit render in a closed shadow root; no data-sitekey and no key in the HTML
    pytest.importorskip("playwright.async_api")
    assert asyncio.run(_turnstile_key()) == "0x4AAAAAAAtestKeyTestKey"


def test_inbox_allowed_requires_gmail_domain():
    # Loop 15 AnnounceKit: the signup inbox's local part on a company domain was let through
    from mvp.signup_tools import inbox_allowed

    assert inbox_allowed("usersim.signups+abc@gmail.com")
    assert inbox_allowed("u.sersimsignups@googlemail.com")
    assert not inbox_allowed("usersim.signups+announcekit@riveralabs.com")
    assert not inbox_allowed("usersimsignups@example.com")
    assert not inbox_allowed("usersimsignups")
