"""Loop 14: reCAPTCHA challenge visibility (Featurebase).

reCAPTCHA keeps its challenge iframe full-size in the DOM and hides it with visibility:hidden on a wrapper.
_CAPTCHA_JS used the bounding box only, so a hidden challenge counted as open and the hints were wrong.
"""
from __future__ import annotations

import asyncio
import os
import shutil

import pytest

from mvp.sim_mcp.sessions import _CAPTCHA_JS

ANCHOR = '<iframe src="https://www.google.com/recaptcha/api2/anchor?ar=1&k=K&size=invisible" width="256" height="60"></iframe>'
BFRAME = '<iframe src="https://www.google.com/recaptcha/api2/bframe?k=K" style="width:1000px;height:600px"></iframe>'


def _chrome() -> str | None:
    return os.environ.get("USERSIM_TEST_CHROME") or shutil.which("google-chrome") or shutil.which("chromium")


async def _state(html: str) -> dict | None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        kw = {"executable_path": _chrome()} if _chrome() else {}
        try:
            b = await p.chromium.launch(headless=True, **kw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"no local browser: {exc!r}"[:120])
        try:
            page = await b.new_page(viewport={"width": 1280, "height": 800})
            await page.route("**/*", lambda r: r.abort())
            await page.set_content(f"<html><body>{html}</body></html>")
            return await page.evaluate(_CAPTCHA_JS)
        finally:
            await b.close()


def _run(html: str) -> dict | None:
    pytest.importorskip("playwright.async_api")
    return asyncio.run(_state(html))


def test_hidden_challenge_is_not_open():
    st = _run(ANCHOR + f'<div style="visibility:hidden;position:absolute;top:0">{BFRAME}</div>')
    assert st == {"kind": "recaptcha", "token_ready": False, "invisible": True}


def test_visible_challenge_is_open():
    st = _run(ANCHOR + f'<div style="position:absolute;top:0">{BFRAME}</div>')
    assert st["kind"] == "recaptcha" and st.get("challenge_open") is True and not st.get("invisible")


def test_zero_opacity_wrapper_is_not_open():
    st = _run(ANCHOR + f'<div style="opacity:0;position:absolute;top:0">{BFRAME}</div>')
    assert st.get("invisible") is True and not st.get("challenge_open")


def test_no_captcha():
    assert _run("<p>hello</p>") is None


class _FakePage:
    """Minimal page for _await_recaptcha_challenge: scripted captcha states, fixed URL."""

    def __init__(self, states, focus_text=False):
        self.states = list(states)
        self.focus_text = focus_text
        self.url = "https://example.test/register"
        self.calls = 0

    async def evaluate(self, js, *a):
        from mvp.sim_mcp import sessions as S

        if js == S._FOCUS_IS_TEXT_JS:
            return self.focus_text
        self.calls += 1
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]


def test_waits_for_challenge_after_submit():
    from mvp.sim_mcp.sessions import _await_recaptcha_challenge

    inv = {"kind": "recaptcha", "token_ready": False, "invisible": True}
    page = _FakePage([inv, inv, inv, {"kind": "recaptcha", "token_ready": False, "challenge_open": True}])
    asyncio.run(_await_recaptcha_challenge(page, page.url, budget_s=5))
    assert page.calls == 4  # stopped as soon as the grid opened


def test_no_wait_when_click_focused_a_text_field():
    from mvp.sim_mcp.sessions import _await_recaptcha_challenge

    page = _FakePage([{"kind": "recaptcha", "token_ready": False, "invisible": True}], focus_text=True)
    asyncio.run(_await_recaptcha_challenge(page, page.url, budget_s=5))
    assert page.calls == 1


def test_no_wait_without_recaptcha():
    from mvp.sim_mcp.sessions import _await_recaptcha_challenge

    page = _FakePage([None])
    asyncio.run(_await_recaptcha_challenge(page, page.url, budget_s=5))
    assert page.calls == 1
