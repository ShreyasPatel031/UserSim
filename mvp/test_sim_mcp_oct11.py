"""Oct 11: judge signup bar with 2-of-3 votes; plain-address hosts (Chatwoot); custom dropdown option picking (Smartlook)."""
from __future__ import annotations

import asyncio
import io
import unittest
from unittest import mock


def _png() -> bytes:
    from PIL import Image

    im = Image.new("RGB", (320, 200), "white")
    for x in range(0, 320, 7):  # some structure so the frame is not "unrendered"
        for y in range(0, 200, 5):
            im.putpixel((x, y), ((x * 3) % 255, (y * 5) % 255, 90))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def _row(verified: bool) -> dict:
    row = {"signup_email": "usersim.signups+t1@gmail.com", "task_prompt": "Create an account ... reach the signed-in dashboard.",
           "site_url": "https://raygun.com/", "final_url": "https://app.raygun.com/onboarding/setup-raygun/",
           "trace": [], "agent_id": "t1__p1__product"}
    if verified:
        row.update(signup_mail=[{"from": "no-reply@raygun.com", "subject": "Verify your email"}], signup_code_used=True)
    return row


class VoteTests(unittest.TestCase):
    def _run(self, row, answers, tmp):
        from mvp.sim_mcp import report as R

        calls = []

        def fake(png, *, task, **kw):
            calls.append(task)
            return answers[len(calls) - 1]

        d = tmp / "sid" / "t1__p1__product" / "screenshots"
        d.mkdir(parents=True)
        (d / "final.png").write_bytes(_png())
        with mock.patch.object(R, "MVP_RUNS_DIR", tmp), mock.patch("mvp.e2e2_gates.judge_goal_screenshot", fake), \
                mock.patch.object(R, "frame_unrendered", lambda png: False), \
                mock.patch("mvp.e2e2_gates.judge_signed_in", lambda *a, **k: {"signed_in": False}):
            verdict, status = asyncio.run(R.judge_run("sid", row))
        return verdict, status, calls

    def test_two_of_three_pass_uses_signup_bar(self):
        import pathlib
        import tempfile

        from mvp.sim_mcp.report import SIGNUP_BAR_TASK

        yes = {"goal_reached": True, "signed_in_app_page": True, "reason": "onboarding inside app"}
        no = {"goal_reached": False, "signed_in_app_page": True, "reason": "not the dashboard"}
        with tempfile.TemporaryDirectory() as t:
            v, status, calls = self._run(_row(True), [no, yes, yes], pathlib.Path(t))
        self.assertEqual(status, "ok")
        self.assertTrue(v["goal_reached"])
        self.assertEqual(v["votes_yes"], 2)
        self.assertEqual(len(v["votes"]), 3)
        self.assertTrue(all(c == SIGNUP_BAR_TASK for c in calls))

    def test_majority_settles_early(self):
        import pathlib
        import tempfile

        no = {"goal_reached": False, "signed_in_app_page": False, "reason": "login form"}
        with tempfile.TemporaryDirectory() as t:
            v, _, calls = self._run(_row(True), [no, no, no], pathlib.Path(t))
        self.assertFalse(v["goal_reached"])
        self.assertEqual(len(calls), 2)

    def test_unverified_signup_single_vote_and_never_passes(self):
        import pathlib
        import tempfile

        yes = {"goal_reached": True, "signed_in_app_page": True, "reason": "x"}
        with tempfile.TemporaryDirectory() as t:
            v, _, calls = self._run(_row(False), [yes], pathlib.Path(t))
        self.assertEqual(len(calls), 1)
        self.assertNotIn("votes", v)
        self.assertFalse(v["goal_reached"])  # hard rule: a signup never passes unverified


class PlainHostTests(unittest.TestCase):
    def test_plain_host_gets_plain_address_others_keep_alias(self):
        import os

        from mvp.signup_inbox import fresh_gmail_address
        from mvp.signup_tools import inbox_allowed

        with mock.patch.dict(os.environ, {"MVP_SIGNUP_PLAIN_HOSTS": "chatwoot.com", "MVP_SIGNUP_EMAIL_DOTS": "0"}):
            plain = fresh_gmail_address("usersim.signups@gmail.com", "www.chatwoot.com", "chatwoot")
            other = fresh_gmail_address("usersim.signups@gmail.com", "smartlook.com", "smartlook")
        self.assertEqual(plain, "usersim.signups@gmail.com")
        self.assertTrue(other.startswith("usersim.signups+smartlook"))
        self.assertTrue(inbox_allowed(plain))


class CustomDropdownTests(unittest.TestCase):
    def test_option_picked_and_options_listed_on_miss(self):
        import shutil

        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        if not chrome:
            self.skipTest("no chrome")
        from mvp.sim_mcp.sessions import _CUSTOM_OPTION_JS

        body = ("<label>Your role*</label><div id=box>Your role*</div>"
                "<ul class='dropdown-menu'><li>Developer</li><li>Product manager</li><li>Marketing</li></ul>"
                "<script>document.querySelectorAll('li').forEach(li=>li.onclick=()=>{box.textContent=li.textContent})</script>")

        async def run():
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                b = await p.chromium.launch(headless=True, executable_path=chrome)
                pg = await b.new_page()
                await pg.set_content(body)
                hit = await pg.evaluate(_CUSTOM_OPTION_JS, "product manager")
                await pg.mouse.click(hit["x"], hit["y"])
                chosen = await pg.inner_text("#box")
                miss = await pg.evaluate(_CUSTOM_OPTION_JS, "CEO")
                await b.close()
                return hit, chosen, miss

        hit, chosen, miss = asyncio.run(run())
        self.assertTrue(hit["ok"])
        self.assertEqual(chosen, "Product manager")
        self.assertFalse(miss["ok"])
        self.assertEqual(miss["options"], ["Developer", "Product manager", "Marketing"])


class HCaptchaTests(unittest.TestCase):
    def test_uuid_sitekey_or_hcaptcha_frame_is_hcaptcha(self):
        from mvp.sim_mcp.server import _is_hcaptcha

        class P:
            def __init__(self, v):
                self.v = v

            async def evaluate(self, js, *a):
                return self.v

        self.assertTrue(asyncio.run(_is_hcaptcha(P(False), {"sitekey": "d0934688-a249-4b30-8047-3abedbca7d3f"})))
        self.assertTrue(asyncio.run(_is_hcaptcha(P(True), {})))
        self.assertFalse(asyncio.run(_is_hcaptcha(P(False), {"sitekey": "6LabcdefghijklmnopqrstuvwxyzABCDEFGHIJKL"})))

    def test_paid_token_refuses_hcaptcha_without_an_attempt(self):
        from mvp import captcha_spend as cs
        from mvp.sim_mcp import server as SV

        class P:
            async def evaluate(self, js, *a):
                return True

        class Sim:
            page = P()
            product_url = "https://www.chatwoot.com/"
            row: dict = {}

        with mock.patch.object(cs, "begin_inrun_attempt", side_effect=AssertionError("attempt counted")):
            out = asyncio.run(SV._paid_token(Sim(), "recaptcha_v2", {}))
        self.assertFalse(out["ok"])
        self.assertEqual(out["type"], "hcaptcha")
