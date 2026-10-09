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


async def _active_value(html: str, js_focus: str, xy: tuple[int, int]):
    from playwright.async_api import async_playwright

    from mvp.sim_mcp.sessions import _ACTIVE_VALUE_JS

    async with async_playwright() as p:
        kw = {"executable_path": _chrome()} if _chrome() else {}
        try:
            b = await p.chromium.launch(headless=True, **kw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"no local browser: {exc!r}"[:120])
        try:
            page = await b.new_page(viewport={"width": 1280, "height": 800})
            await page.set_content(html)
            await page.evaluate(js_focus)
            return await page.evaluate(_ACTIVE_VALUE_JS, list(xy))
        finally:
            await b.close()


BOXES = "".join(f'<input id="b{i}" maxlength="1" style="position:absolute;left:{40 + 50 * i}px;top:20px;width:40px">' for i in range(6))
PLAIN_BOXES = BOXES.replace(' maxlength="1"', "")


def test_split_code_boxes_skip_the_wipe_check():
    pytest.importorskip("playwright.async_api")
    # focus advanced from box 0 (clicked) to box 5: no wipe check (would retype and garble the code)
    v = asyncio.run(_active_value(PLAIN_BOXES, "document.getElementById('b0').value='1';document.getElementById('b5').focus()", (60, 30)))
    assert v is None
    v = asyncio.run(_active_value(BOXES, "const e=document.getElementById('b0');e.value='1';e.focus()", (60, 30)))
    assert v is None


def test_plain_field_still_checked():
    pytest.importorskip("playwright.async_api")
    html = '<input id="e" style="position:absolute;left:40px;top:20px;width:300px">'
    v = asyncio.run(_active_value(html, "const e=document.getElementById('e');e.value='abc';e.focus()", (100, 30)))
    assert v == "abc"


def test_alias_rejection_canonical_wording():
    from mvp.sim_mcp.sessions import _ALIAS_RE

    assert _ALIAS_RE.search("Invalid `email` param: Value must be a valid email address in its canonical form")
    assert _ALIAS_RE.search("Please use a canonical email address")
    assert not _ALIAS_RE.search("Canonical URL for this page")
    assert _ALIAS_RE.search("Email aliases (+) are not allowed")
