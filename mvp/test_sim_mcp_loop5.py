"""Loop 5 fixes (Grok Bot client findings on formbold / fabform / litlyx). Offline: no Browserbase, no LLM."""
from __future__ import annotations

import asyncio
import io
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from PIL import Image, ImageDraw


def _png(im: Image.Image) -> bytes:
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def spinner_frame() -> bytes:  # FormBold's stuck /dashboard: white page, one small ring
    im = Image.new("RGB", (1280, 800), "white")
    ImageDraw.Draw(im).ellipse((628, 388, 652, 412), outline=(90, 80, 220), width=2)
    return _png(im)


def dim_backdrop_frame() -> bytes:  # Litlyx: a leftover dark backdrop over a real page
    im = Image.new("RGB", (1280, 800), (51, 51, 51))
    d = ImageDraw.Draw(im)
    for i in range(14):  # dimmed text lines + a button
        d.rectangle((480, 90 + i * 22, 480 + 300 + (i % 4) * 40, 98 + i * 22), fill=(72, 72, 72))
    d.rectangle((480, 420, 800, 446), fill=(20, 20, 20))
    d.rectangle((10, 10, 120, 24), fill=(80, 80, 80))
    return _png(im)


def page_frame() -> bytes:
    im = Image.new("RGB", (1280, 800), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 1280, 60), fill=(30, 30, 60))
    for i in range(20):
        d.rectangle((100, 100 + i * 30, 900, 112 + i * 30), fill=(120, 120, 120))
    return _png(im)


ROW = {"signup_email": "usersim.signups+x1@gmail.com", "task_prompt": "Create a new account and reach the dashboard",
       "signup_mail": [{"subject": "Confirm your email", "sender": "Litlyx"}]}


class JudgeHardRulesTests(unittest.TestCase):
    def test_spinner_frame_is_unrendered_dim_backdrop_is_not(self):
        from mvp.sim_mcp.report import frame_unrendered

        self.assertTrue(frame_unrendered(spinner_frame()))
        self.assertTrue(frame_unrendered(_png(Image.new("RGB", (1280, 800), (10, 10, 10)))))
        self.assertFalse(frame_unrendered(dim_backdrop_frame()))
        self.assertFalse(frame_unrendered(page_frame()))
        big = Image.open(io.BytesIO(dim_backdrop_frame())).resize((2560, 1440))
        self.assertFalse(frame_unrendered(_png(big)))

    def test_formbold_spinner_never_passes(self):
        from mvp.sim_mcp.report import apply_hard_rules

        row = {**ROW, "opened_links": ["https://formbold.com/verify?token=abc"]}
        v = apply_hard_rules(row, {"goal_reached": True, "reason": "dashboard"}, {"signed_in_app_page": True}, spinner_frame())
        self.assertFalse(v["goal_reached"])
        self.assertTrue(v["page_unrendered"])

    def test_judge_loading_flag_never_passes(self):
        from mvp.sim_mcp.report import apply_hard_rules

        row = {**ROW, "opened_links": ["https://x.io/verify?token=abc"]}
        v = apply_hard_rules(row, {"goal_reached": True, "reason": "ok"}, {"page_loading": True, "signed_in_app_page": True}, page_frame())
        self.assertFalse(v["goal_reached"])

    def test_fabform_unverified_signup_never_passes(self):
        from mvp.sim_mcp.report import apply_hard_rules

        row = {"signup_email": "usersim.signups+fab@gmail.com", "task_prompt": "Create an account, confirm my email"}
        v = apply_hard_rules(row, {"goal_reached": True, "reason": "My forms"}, {"signed_in_app_page": True}, page_frame())
        self.assertFalse(v["goal_reached"])
        self.assertIn("not email-verified", v["reason"])
        # a signup task with no alias issued at all is not verified either
        v2 = apply_hard_rules({"task_prompt": "Sign up for Acme"}, {"goal_reached": True, "reason": "x"}, {}, page_frame())
        self.assertFalse(v2["goal_reached"])

    def test_verified_signed_in_still_overrides(self):
        from mvp.sim_mcp.report import apply_hard_rules

        row = {**ROW, "opened_links": ["https://sendibt3.com/tr/cl/abc"], "opened_link_texts": {"https://sendibt3.com/tr/cl/abc": "Confirm my email"}}
        v = apply_hard_rules(row, {"goal_reached": False, "reason": "install page"}, {"signed_in_app_page": True}, dim_backdrop_frame())
        self.assertTrue(v["goal_reached"])

    def test_non_signup_task_unaffected(self):
        from mvp.sim_mcp.report import apply_hard_rules, is_signup_goal

        row = {"task_prompt": "Find the free plan limit without creating an account."}
        self.assertFalse(is_signup_goal(row))
        self.assertFalse(is_signup_goal({"task_prompt": "Compare pricing without signing up"}))
        v = apply_hard_rules(row, {"goal_reached": True, "reason": "pricing"}, {}, page_frame())
        self.assertTrue(v["goal_reached"])


class TrackingLinkTests(unittest.TestCase):
    TRACKERS = ["https://sendibt3.com/tr/cl/AbCdEf123", "https://u1234.ct.sendgrid.net/ls/click?upn=xyz",
                "https://acme.us1.list-manage.com/track/click?u=1&id=2", "https://links.umami.is/CL0/https:%2F%2Fumami.is/1/abc"]

    def test_trackers_detected(self):
        from mvp.signup_inbox import is_tracking_link

        for u in self.TRACKERS:
            self.assertTrue(is_tracking_link(u), u)
        self.assertFalse(is_tracking_link("https://sendfox.com/account/verify-email/abc"))

    def test_anchor_text_or_chain_accepts_tracker(self):
        from mvp.signup_inbox import verification_link

        u = self.TRACKERS[0]
        self.assertFalse(verification_link(u))
        self.assertTrue(verification_link(u, "Confirm your email"))
        self.assertTrue(verification_link(u, "Verify account"))
        self.assertFalse(verification_link(u, "Read our FAQ"))
        self.assertTrue(verification_link(u, chain=[u, "https://dashboard.litlyx.com/auth/confirm?t=1"]))
        self.assertFalse(verification_link(u, chain=[u, "https://help.litlyx.com/"]))

    def test_resolve_refuses_private_hosts(self):
        from mvp.signup_inbox import resolve_redirects

        self.assertEqual(resolve_redirects("http://127.0.0.1:9/tr/cl/x"), ["http://127.0.0.1:9/tr/cl/x"])
        self.assertEqual(resolve_redirects("http://169.254.169.254/latest/meta-data/"), ["http://169.254.169.254/latest/meta-data/"])

    def test_resolve_follows_location_but_never_requests_the_verify_hop(self):
        import mvp.signup_inbox as si

        hits: list[str] = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                hits.append(self.path)
                if self.path.startswith("/tr/cl/"):
                    self.send_response(302)
                    self.send_header("Location", "/hop2")
                elif self.path == "/hop2":
                    self.send_response(301)
                    self.send_header("Location", "/account/verify-email/abc")
                else:
                    self.send_response(200)
                self.end_headers()

            def log_message(self, *a):  # noqa: ANN002
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{srv.server_port}"
            with mock.patch.object(si, "_public_host", return_value=True):
                chain = si.resolve_redirects(base + "/tr/cl/abc")
                ok = si.verification_link(base + "/tr/cl/abc", resolve=True)
        finally:
            srv.shutdown()
        self.assertEqual(chain[-1], base + "/account/verify-email/abc")
        self.assertTrue(ok)
        self.assertNotIn("/account/verify-email/abc", hits)  # checking a link must never verify it

    def test_signup_verified_uses_texts_and_chains(self):
        from mvp.sim_mcp.report import signup_verified

        u = self.TRACKERS[0]
        self.assertFalse(signup_verified({**ROW, "opened_links": [u]}))
        self.assertTrue(signup_verified({**ROW, "opened_links": [u], "opened_link_texts": {u: "Confirm my email"}}))
        self.assertTrue(signup_verified({**ROW, "opened_links": [u], "opened_link_chains": {u: [u, "https://app.x.io/verify/1"]}}))

    def test_rank_prefers_confirm_button_behind_tracker(self):
        from mvp.signup_inbox import rank_links

        links = ["https://litlyx.com/blog/launch", "https://sendibt3.com/tr/cl/AAA", "https://sendibt3.com/tr/cl/BBB"]
        anchors = {"https://sendibt3.com/tr/cl/BBB": "Confirm your email"}
        self.assertEqual(rank_links(links, "litlyx.com", anchors)[0], "https://sendibt3.com/tr/cl/BBB")


class FrameAndSecretTests(unittest.TestCase):
    def test_fit_frame_makes_1280x800(self):
        from mvp.sim_mcp.sessions import fit_frame

        for size in [(2560, 1440), (2560, 1600), (1280, 800), (1920, 1080)]:
            out = Image.open(io.BytesIO(fit_frame(_png(Image.new("RGB", size, "white")))))
            self.assertEqual(out.size, (1280, 800), size)

    def test_password_masked_in_trace_and_observation(self):
        from mvp.sim_mcp.sessions import SimSession, describe_action, mask_secrets, scrub

        sim = SimSession(id="t", study=None, product_url="https://x.io", task="", persona="")
        sim.identity = {"password": "Kl0NC4JWTF5er8!58Aa"}
        a = mask_secrets(sim, {"type": "type", "text": "Kl0NC4JWTF5er8!58Aa", "x": 1, "y": 2})
        self.assertNotIn("Kl0NC4", describe_action(a))
        obs = scrub(sim, {"fields": [{"kind": "password", "label": "Kl0NC4JWTF5er8!58Aa"}], "png": b"\x89PNG"})
        self.assertNotIn("Kl0NC4", str(obs["fields"]))
        self.assertEqual(obs["png"], b"\x89PNG")

    def test_clear_cookies_is_a_valid_action(self):
        from mvp.sim_mcp.sessions import validate_action

        self.assertEqual(validate_action({"type": "clear_cookies"}, "https://x.io")["type"], "clear_cookies")


def _chromium():
    try:
        from playwright.async_api import async_playwright  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


HTML = """<html><body style="margin:0">
<form style="padding:20px">
 <label for=e>Email</label><input id=e name=email value="usersim.signups+a@gmail.com"><br>
 <input id=p type=password name=pw><br>
 <label class="tos"><input type=checkbox id=tos name=terms style="position:absolute;opacity:0;width:1px;height:1px">
   <span>I agree to the Terms</span></label><br>
 <div class="form-error" role="alert">Email aliases not allowed</div>
 <a id=go href="/next">Next</a>
</form>
<script>
 document.getElementById('go').addEventListener('click', e => { e.preventDefault(); setTimeout(() => location.href = '/next', 500); });
 setTimeout(() => { throw new Error('boom in app bundle'); }, 10);
</script></body></html>"""


@unittest.skipUnless(_chromium(), "playwright not installed")
class BrowserTests(unittest.TestCase):
    def _run(self, fn):
        async def main():
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": 2560, "height": 1440})
                page = await ctx.new_page()

                async def route(r):
                    await r.fulfill(status=200, content_type="text/html",
                                    body=HTML if not r.request.url.endswith("/next") else "<h1>Next page</h1>")

                await page.route("http://usersim.test/**", route)
                try:
                    return await fn(page)
                finally:
                    await b.close()

        try:
            return asyncio.run(main())
        except Exception as exc:  # noqa: BLE001
            if "Executable doesn't exist" in str(exc):
                self.skipTest("chromium not installed")
            raise

    def test_viewport_forced_to_1280x800(self):
        from mvp.sim_mcp.sessions import ensure_viewport

        async def fn(page):
            await page.goto("http://usersim.test/")
            await ensure_viewport(page)
            png = await page.screenshot()
            return await page.evaluate("() => [innerWidth, innerHeight]"), Image.open(io.BytesIO(png)).size

        dims, shot = self._run(fn)
        self.assertEqual(dims, [1280, 800])
        self.assertEqual(shot, (1280, 800))

    def test_fields_mask_password_list_terms_checkbox_and_errors(self):
        from mvp.sim_mcp.sessions import _ERRORS_JS, _FIELDS_JS

        async def fn(page):
            await page.goto("http://usersim.test/")
            await page.fill("#p", "SuperSecret!99Aa")
            await asyncio.sleep(0.1)
            return await page.evaluate(_FIELDS_JS), await page.evaluate(_ERRORS_JS)

        fields, errors = self._run(fn)
        self.assertNotIn("SuperSecret", str(fields))
        boxes = [f for f in fields if f["kind"] == "checkbox"]
        self.assertTrue(boxes and "Terms" in boxes[0]["label"], fields)
        self.assertIn("Email aliases not allowed", errors)

    def test_click_that_navigates_waits_for_new_page_and_errors_collected(self):
        from mvp.sim_mcp.sessions import SimSession, _await_navigation, _watch_page

        async def fn(page):
            sim = SimSession(id="t", study=None, product_url="http://usersim.test/", task="", persona="")
            _watch_page(sim, page)
            await page.goto("http://usersim.test/")
            await asyncio.sleep(0.2)
            before = page.url
            await page.click("#go")
            await _await_navigation(page, before)
            return page.url, list(sim.page_errors)

        url, errs = self._run(fn)
        self.assertTrue(url.endswith("/next"))
        self.assertTrue(any("boom in app bundle" in e for e in errs), errs)

    def test_clear_cookies_logs_out(self):
        from mvp.sim_mcp.sessions import _execute

        async def fn(page):
            await page.goto("http://usersim.test/")
            await page.context.add_cookies([{"name": "sid", "value": "1", "url": "http://usersim.test/"}])
            await page.evaluate("localStorage.setItem('token', 'abc')")
            await _execute(page, {"type": "clear_cookies"})
            return await page.context.cookies(), await page.evaluate("localStorage.getItem('token')")

        cookies, token = self._run(fn)
        self.assertEqual(cookies, [])
        self.assertIsNone(token)


class ProofDetailTests(unittest.TestCase):
    def test_detail_differs_for_pass_and_fail(self):
        from mvp.sim_mcp import report

        study = {"id": "s", "driver": report.DRIVER}
        base = {"site_url": "https://x.io", "page_url": "https://x.io/", "trace": [], "signup_email": "usersim.signups+q@gmail.com"}
        bad = {c["name"]: c for c in report.proof_checks(study, base, "ok")["checks"]}
        good_row = {**base, "signup_mail": [{"subject": "Verify"}], "opened_links": ["https://x.io/verify?t=1"]}
        good = {c["name"]: c for c in report.proof_checks(study, good_row, "ok")["checks"]}
        self.assertFalse(bad["signup_verified"]["pass"])
        self.assertTrue(good["signup_verified"]["pass"])
        self.assertNotEqual(bad["signup_verified"]["detail"], good["signup_verified"]["detail"])
        self.assertIn("NOT", bad["signup_verified"]["detail"])
        self.assertNotEqual(bad["screenshots_real"]["detail"], "0 steps, every screenshot shows a rendered page")


if __name__ == "__main__":
    unittest.main()
