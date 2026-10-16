"""Loop 16: reCAPTCHA v3 token refresh, v3 action capture, paid solve after a visible captcha rejection (FeedBear).

FeedBear (reCAPTCHA v3) mints its token in onSubmit() when Register is clicked and posts it; in plain Chrome that
works. From the Browserbase browser the site answers ?captcha_failed=true, and it refused a standard paid v3 token too
(the token was posted, checked with an intercepted POST): the site wants a higher score. The guards below stop paying
twice on one page and stop paying for v3 again after a paid token was refused.
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


class _Page:
    def __init__(self, marker=False):
        self.marker = marker

    async def evaluate(self, js, *a):
        if "__usersimPaidAt = Date.now()" in js:
            self.marker = True
            return None
        if "__usersimPaidAt" in js:
            return self.marker
        return None


class _Sim:
    def __init__(self, page, **row):
        self.page = page
        self.product_url = "https://feedbear.com/"
        self.row = {"signup_email": "x@example.invalid", **row}


def _patch(monkeypatch, kind="recaptcha_v3", rejected=True, token_ready=True):
    from mvp import captcha as cap
    from mvp import captcha_spend as cs
    from mvp.sim_mcp import server as SV
    from mvp.sim_mcp import sessions as S

    bought = []

    async def state(page):
        return {"kind": kind, "token_ready": token_ready}

    async def rej(page):
        return rejected

    async def paid(sim, k, info):
        bought.append(k)
        return {"ok": True}

    async def sk(page):
        return {}

    monkeypatch.setenv("MVP_MCP_PAID_CAPTCHA", "1")
    monkeypatch.setattr(cs, "paid_hosts", lambda: {"feedbear.com"})
    monkeypatch.setattr(S, "captcha_state", state)
    monkeypatch.setattr(SV, "_captcha_rejected", rej)
    monkeypatch.setattr(SV, "_paid_token", paid)
    monkeypatch.setattr(cap, "detect_sitekey", sk)
    return SV, bought


def test_one_paid_token_per_page_load(monkeypatch):
    SV, bought = _patch(monkeypatch, kind="recaptcha_v2")
    sim = _Sim(_Page())
    assert asyncio.run(SV._maybe_paid_presolve(sim))["ok"]
    assert asyncio.run(SV._maybe_paid_presolve(sim)) is None  # same page, banner still showing: no second token
    sim.page.marker = False  # navigation
    assert asyncio.run(SV._maybe_paid_presolve(sim))["ok"]
    assert bought == ["recaptcha_v2", "recaptcha_v2"]


def test_no_second_v3_token_after_refusal(monkeypatch):
    SV, bought = _patch(monkeypatch)
    sim = _Sim(_Page(), capsolver_v3_paid=1, capsolver_tries=1)
    out = asyncio.run(SV._maybe_paid_presolve(sim))
    assert out["ok"] is False and "score" in out["detail"]
    assert bought == [] and sim.row["v3_paid_rejected"] is True


def test_paid_v3_token_is_posted():
    """The page's own onSubmit calls grecaptcha.execute and overwrites the field; the paid override must win."""
    if not _chrome():
        pytest.skip("no chrome")
    from mvp.sim_mcp.server import _PAID_JS

    body = ("<form id=f action='/x'><input type=hidden name=g-recaptcha-response id=g></form><script>" + STUB +
            "window.sub=function(){grecaptcha.ready(function(){grecaptcha.execute('k',{action:'submit'})"
            ".then(function(t){document.getElementById('g').value=t;window.__posted=t;});});};</script>")

    async def run():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            b = await p.chromium.launch(headless=True, executable_path=_chrome())
            ctx = await b.new_context()
            await ctx.add_init_script(V3_ACTION_HOOK)
            pg = await ctx.new_page()
            await pg.set_content(body)
            await pg.evaluate(_PAID_JS, ["recaptcha_v3", "PAIDTOKEN"])
            await pg.evaluate("window.sub()")
            await pg.wait_for_timeout(200)
            out = await pg.evaluate("window.__posted")
            await b.close()
            return out

    assert asyncio.run(run()) == "PAIDTOKEN"
