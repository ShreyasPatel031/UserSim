"""Loop 6 fixes (live reruns + Grok Bot client findings on litlyx / databuddy). Offline: no Browserbase, no LLM."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mvp.test_sim_mcp_loop5 import _chromium, page_frame

FORM = """<html><body style="margin:0;font:16px sans-serif">
<div style="padding:20px">
 <input id=e name=email placeholder="Email" style="width:300px;height:30px"><br><br>
 <input id=p type=password name=pw placeholder="Password" style="width:300px;height:30px"><br><br>
 <!-- bot traps / hidden -->
 <input type=checkbox id=trap name=agree_hidden style="position:absolute;left:700px;top:560px;opacity:0;width:16px;height:16px">
 <input name=website_hp id=hp placeholder="Website" style="width:200px;height:30px">
 <input name=company placeholder="Company" style="position:absolute;top:900px;width:200px;height:30px">
 <button id=covered style="position:absolute;left:600px;top:300px;width:120px;height:40px">Hidden submit</button>
 <div id="crisp-chatbox" style="position:absolute;left:580px;top:280px;width:200px;height:90px;background:#fff"></div>
 <!-- real terms checkbox: hidden input, visible text label -->
 <label><input type=checkbox id=tos name=terms style="position:absolute;opacity:0;width:1px;height:1px"><span>I agree to the Terms</span></label><br><br>
 <!-- utility classes that are not errors -->
 <button class="aria-invalid:ring-destructive hover:text-error px-4">Save changes</button>
 <nav><a class="text-error-foreground" href="#">Analytics menu</a></nav>
 <div class="focus:border-error rounded">Workspace settings</div>
 <p class="field-error">Password is too short</p>
 <a id=tab href="/tab" target=_blank style="position:absolute;left:20px;top:720px">Start Free</a>
</div>
<script>
 // late hydration: the first value typed into the email box is wiped once, 400 ms after the first keystroke
 let wiped = false;
 document.getElementById('e').addEventListener('input', () => {
   if (!wiped) { wiped = true; setTimeout(() => { document.getElementById('e').value = ''; document.getElementById('e').blur(); }, 400); }
 });
</script></body></html>"""


@unittest.skipUnless(_chromium(), "playwright not installed")
class Loop6BrowserTests(unittest.TestCase):
    def _run(self, fn):
        async def main():
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                b = await p.chromium.launch()
                ctx = await b.new_context(viewport={"width": 1280, "height": 800})
                page = await ctx.new_page()

                async def route(r):
                    body = FORM if not r.request.url.endswith("/tab") else "<title>Signup</title><h1>Register</h1>"
                    await r.fulfill(status=200, content_type="text/html", body=body)

                await ctx.route("http://usersim.test/**", route)
                try:
                    return await fn(ctx, page)
                finally:
                    await b.close()

        try:
            return asyncio.run(main())
        except Exception as exc:  # noqa: BLE001
            if "Executable doesn't exist" in str(exc):
                self.skipTest("chromium not installed")
            raise

    def test_type_survives_late_rerender(self):
        from mvp.sim_mcp.sessions import _execute

        async def fn(ctx, page):
            await page.goto("http://usersim.test/")
            box = await page.locator("#e").bounding_box()
            await _execute(page, {"type": "type", "text": "usersim.signups+t@gmail.com",
                                  "x": int(box["x"] + 20), "y": int(box["y"] + 10)})
            await asyncio.sleep(0.6)
            return await page.input_value("#e")

        self.assertEqual(self._run(fn), "usersim.signups+t@gmail.com")

    def test_click_opening_new_tab_switches_session(self):
        from mvp.sim_mcp.sessions import SimSession, _await_navigation

        async def fn(ctx, page):
            sim = SimSession(id="t", study=None, product_url="http://usersim.test/", task="", persona="")
            sim.page, sim.context = page, ctx
            ctx.on("page", lambda p: setattr(sim, "new_page", p))
            await page.goto("http://usersim.test/")
            before = page.url
            await page.click("#tab")
            await _await_navigation(page, before, [], sim=sim)
            return sim.page.url, await sim.page.evaluate("() => [innerWidth, innerHeight]")

        url, size = self._run(fn)
        self.assertTrue(url.endswith("/tab"), url)
        self.assertEqual(size, [1280, 800])

    def test_errors_only_real_errors(self):
        from mvp.sim_mcp.sessions import _ERRORS_JS

        async def fn(ctx, page):
            await page.goto("http://usersim.test/")
            return await page.evaluate(_ERRORS_JS)

        errs = self._run(fn)
        self.assertIn("Password is too short", errs)
        for label in ("Save changes", "Analytics menu", "Workspace settings"):
            self.assertNotIn(label, " | ".join(errs))

    def test_hidden_offscreen_trap_and_covered_controls_not_clickable(self):
        from mvp.sim_mcp.sessions import _FIELDS_JS, _split_fields

        async def fn(ctx, page):
            await page.goto("http://usersim.test/")
            return _split_fields(await page.evaluate(_FIELDS_JS))

        out = self._run(fn)
        labels = [f["label"] for f in out["fields"]]
        self.assertIn("Email", labels)
        self.assertTrue(any("Terms" in lab for lab in labels), labels)
        for bad in ("Website", "Company", "Hidden submit", "agree_hidden"):
            self.assertNotIn(bad, labels)
        self.assertFalse(any(f.get("y", 0) > 800 for f in out["fields"]))
        hidden = {h["label"]: h["reason"] for h in out.get("hidden_fields", [])}
        self.assertIn("bot trap", hidden.get("Website", ""))
        self.assertIn("below the fold", hidden.get("Company", ""))
        self.assertIn("agree_hidden", hidden)
        self.assertIn("chat widget", hidden.get("Hidden submit", ""))  # Formester: Crisp chat covered "Sign up"
        self.assertTrue(all("x" not in h for h in out["hidden_fields"]))


ROW = {"signup_email": "usersim.signups+lit@gmail.com", "agent_id": "a1",
       "task_prompt": "Create a free Litlyx account, confirm my email, and get to my analytics dashboard.",
       "final_url": "https://dashboard.litlyx.com/"}


class SecondLookJudgeTests(unittest.TestCase):
    def _judge(self, verified: bool, second: bool):
        from mvp.sim_mcp import report

        calls = []

        def goal(*a, **k):
            return {"goal_reached": False, "signed_in_app_page": False, "page_loading": False,
                    "reason": "install page, not dashboard"}

        def look(png, **k):
            calls.append(k)
            return {"signed_in": second, "evidence": "account menu shows the signup email"}

        with tempfile.TemporaryDirectory() as tmp:
            shots = Path(tmp) / "s1" / "a1" / "screenshots"
            shots.mkdir(parents=True)
            (shots / "final.png").write_bytes(page_frame())
            with mock.patch.object(report, "MVP_RUNS_DIR", Path(tmp)), \
                 mock.patch("mvp.e2e2_gates.judge_goal_screenshot", goal), \
                 mock.patch("mvp.e2e2_gates.judge_signed_in", look), \
                 mock.patch.object(report, "signup_verified", lambda row: verified):
                verdict, status = asyncio.run(report.judge_run("s1", dict(ROW)))
        return verdict, status, calls

    def test_verified_signup_on_signed_in_setup_page_passes(self):
        verdict, status, calls = self._judge(verified=True, second=True)
        self.assertEqual(status, "ok")
        self.assertTrue(verdict["goal_reached"], verdict)
        self.assertEqual(calls[0]["account_email"], ROW["signup_email"])
        self.assertIn("signed_in_check", verdict)

    def test_second_look_says_signed_out_stays_fail(self):
        verdict, _, _ = self._judge(verified=True, second=False)
        self.assertFalse(verdict["goal_reached"])

    def test_unverified_never_asks_and_never_passes(self):
        verdict, _, calls = self._judge(verified=False, second=True)
        self.assertFalse(verdict["goal_reached"])
        self.assertEqual(calls, [])


class IdentityLoopTests(unittest.TestCase):
    """FormBold: the alias-rejected text stays on the page; Gemini called signup_identity 30 times."""

    def _sim(self, address):
        from types import SimpleNamespace

        return SimpleNamespace(id="s1", inbox=SimpleNamespace(address=address), row={},
                               identity={"email": address, "password": "pw"})

    def _obs(self):
        return {"step": 3, "url": "https://formbold.com/auth/register", "title": "", "steps_left": 10,
                "seconds_left": 100, "alias_rejected": True, "png": page_frame()}

    def test_hint_after_switching_to_no_plus_says_retype(self):
        from mvp.sim_mcp import server

        content = server._obs_content(self._sim("testin.box@gmail.com"), self._obs())
        text = str(content)
        self.assertIn("already have the no-plus address", text)
        self.assertNotIn("call usersim_signup_identity with no_plus=true", text)

    def test_half_filled_form_names_empty_boxes(self):
        from mvp.sim_mcp import server

        obs = dict(self._obs(), alias_rejected=False, fields=[
            {"kind": "email", "label": "Email", "filled": True, "x": 1, "y": 1},
            {"kind": "password", "label": "Password", "filled": True, "x": 1, "y": 2},
            {"kind": "password", "label": "Confirm Password", "filled": False, "x": 1, "y": 3},
            {"kind": "button", "label": "Sign up", "x": 1, "y": 4}])
        text = str(server._obs_content(self._sim("usersim.signups+a@gmail.com"), obs))
        self.assertIn("unfilled_fields", text)
        self.assertIn("Confirm Password", text)

    def test_repeat_identity_calls_are_refused_after_three(self):
        import json

        from mvp.sim_mcp import server

        sim = self._sim("testin.box@gmail.com")
        with mock.patch.object(server.S, "get_session", lambda sid: sim):
            outs = [json.loads(asyncio.run(server.usersim_signup_identity("s1", no_plus=True))) for _ in range(3)]
        self.assertIn("do not call", outs[0]["next"])
        self.assertIn("error", outs[2])
        self.assertEqual(outs[2]["email"], "testin.box@gmail.com")


class SettleFinalTests(unittest.TestCase):
    """FormBold: the client finished right after 'Go to dashboard'; final.png was the loading spinner."""

    def _run(self, frames):
        from types import SimpleNamespace

        from mvp.sim_mcp import sessions as S
        from mvp.test_sim_mcp_loop5 import spinner_frame

        it = iter(frames)

        async def shot(page, timeout_ms=0):
            return next(it)

        async def noop(*a, **k):
            return None

        async def text(page):
            return "Dashboard Forms"

        with tempfile.TemporaryDirectory() as tmp:
            shots = Path(tmp) / "st" / "a1" / "screenshots"
            shots.mkdir(parents=True)
            (shots / "final.png").write_bytes(spinner_frame())
            page = SimpleNamespace(url="https://formbold.com/dashboard")
            sim = SimpleNamespace(closed=False, page=page, study=SimpleNamespace(id="st"), agent_id="a1", row={}, new_page=None)
            with mock.patch.object(S, "MVP_RUNS_DIR", Path(tmp)), mock.patch.object(S, "_screenshot", shot), \
                 mock.patch.object(S, "ensure_viewport", noop), mock.patch.object(S, "_page_text", text), \
                 mock.patch("mvp.opening_shot.upload_screenshot", noop), mock.patch.object(S.asyncio, "sleep", noop):
                replaced = asyncio.run(S.settle_final(sim, max_s=5))
                final = (shots / "final.png").read_bytes()
        return replaced, final, sim.row

    def test_spinner_replaced_once_page_paints(self):
        from mvp.sim_mcp.report import frame_unrendered
        from mvp.test_sim_mcp_loop5 import spinner_frame

        replaced, final, row = self._run([spinner_frame(), page_frame()])
        self.assertTrue(replaced)
        self.assertFalse(frame_unrendered(final))
        self.assertEqual(row["final_dom"], "Dashboard Forms")

    def test_stuck_spinner_stays_and_is_noted(self):
        from mvp.sim_mcp.report import frame_unrendered
        from mvp.test_sim_mcp_loop5 import spinner_frame

        with mock.patch("time.time", side_effect=[0, 1, 2, 3, 4, 9, 9, 9, 9, 9]):
            replaced, final, row = self._run([spinner_frame()] * 10)
        self.assertFalse(replaced)
        self.assertTrue(frame_unrendered(final))
        self.assertIn("still blank", row["final_settle"])


class EngineVersionTests(unittest.TestCase):
    def test_engine_version_carries_content_id(self):
        from mvp import version

        version.engine_version.cache_clear()
        version.content_id.cache_clear()
        v = version.engine_version()
        cid = version.content_id()
        self.assertTrue(cid)
        self.assertIn(f"+tree.{cid}", v)
        self.assertIn("content_id", version.stamp())


if __name__ == "__main__":
    unittest.main()


class LetterOnlyCodeTests(unittest.TestCase):
    """Loop 12 (Frill): the code is six lowercase letters after 'verification code is:'."""

    def test_letters_only_code_after_explicit_wording(self):
        from mvp.email_codes import _find_code
        body = "Hey! Your email verification code is: qwzvbk This code will expire in 15 minutes."
        self.assertEqual(_find_code("Email Verification Code", body), "qwzvbk")

    def test_plain_words_are_not_codes(self):
        from mvp.email_codes import _find_code
        self.assertIsNone(_find_code("Welcome", "Your verification code is: below. Thanks for joining"))
        self.assertIsNone(_find_code("Confirm your account", "Click the button to confirm your email address."))

    def test_digit_codes_still_win(self):
        from mvp.email_codes import _find_code
        self.assertEqual(_find_code("Your code", "Your verification code is: 482913"), "482913")


class CodeIsColonTests(unittest.TestCase):
    """Loop 12 (Frill, 2nd mail): 'verification code is: 5ab12c' was missed because 'is:' broke _CODE_NEAR."""

    def test_mixed_code_after_is_colon_keeps_case(self):
        from mvp.email_codes import _find_code
        body = "Hey! Your email verification code is: 7xq21z \n\r\n This code will expire in 15 minutes."
        self.assertEqual(_find_code("Email Verification Code", body), "7xq21z")

    def test_atlassian_subject_code_still_found(self):
        from mvp.email_codes import _find_code
        self.assertEqual(_find_code("EV7DUU is your verification code", ""), "EV7DUU")

    def test_code_is_valid_is_not_a_code(self):
        from mvp.email_codes import _find_code
        self.assertIsNone(_find_code("Welcome", "This code is valid for ten minutes."))


class HostBrandLabelTests(unittest.TestCase):
    """Loop 12 (Frill): host app.frill.co gave token 'app', which the Frill mail never contains."""

    def test_code_found_for_app_subdomain_host(self):
        import email
        from unittest import mock
        from mvp import email_codes as ec
        msg = email.message_from_string(
            "From: Notifications <noreply@frill.co>\nTo: usersim.signups+t1@gmail.com\n"
            "Subject: Email Verification Code\n\nYour email verification code is: 7xq21z\n"
        )
        with mock.patch.object(ec, "_imap_creds", return_value=("usersim.signups@gmail.com", "x")), \
                mock.patch.object(ec, "_iter_recent_messages", return_value=iter([msg])):
            self.assertEqual(ec.latest_signup_code("usersim.signups+t1@gmail.com", host="app.frill.co"), "7xq21z")


class BlockedOffsiteTests(unittest.TestCase):
    """Loop 13 (UptimeRobot): an 'Open Yahoo Mail' button led into Yahoo's signup form."""

    def test_webmail_and_social_hosts_are_blocked(self):
        from mvp.sim_mcp import sessions as S
        p = "https://dashboard.uptimerobot.com/sign-up/"
        for u in ("https://mail.yahoo.com/", "https://login.yahoo.com/account/create?x=1",
                  "https://outlook.live.com/mail/", "https://mail.google.com/mail/u/0/", "https://x.com/i/flow/signup"):
            self.assertTrue(S.blocked_offsite(u, p), u)

    def test_product_and_its_auth_hosts_are_not_blocked(self):
        from mvp.sim_mcp import sessions as S
        p = "https://dashboard.uptimerobot.com/sign-up/"
        for u in ("https://uptimerobot.com/dashboard", "https://dashboard.uptimerobot.com/monitors",
                  "https://foo.clerk.accounts.dev/sign-up", "https://box.com/", "https://max.com/"):
            self.assertFalse(S.blocked_offsite(u, p), u)

    def test_product_that_is_itself_listed_is_not_blocked(self):
        from mvp.sim_mcp import sessions as S
        self.assertFalse(S.blocked_offsite("https://www.linkedin.com/signup", "https://www.linkedin.com/"))


class WaitRenderedTests(unittest.TestCase):
    """Loop 13 (LogSnag): step 0 was captured while the SPA was still a white frame."""

    @staticmethod
    def _png(blank: bool) -> bytes:
        import io
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (1280, 800), "white")
        if not blank:
            d = ImageDraw.Draw(im)
            for i in range(0, 800, 20):
                d.rectangle([100, i, 1100, i + 8], fill="black")
        buf = io.BytesIO(); im.save(buf, "PNG"); return buf.getvalue()

    def test_waits_until_painted(self):
        from mvp.sim_mcp import sessions as S
        shots = [self._png(True), self._png(True), self._png(False)]
        calls = []

        class Page:
            async def screenshot(self, **kw):
                calls.append(1)
                return shots[min(len(calls) - 1, 2)]

        orig = S.asyncio.sleep
        async def fast(_s):
            return None
        S.asyncio.sleep = fast
        try:
            asyncio.run(S._wait_rendered(Page(), budget_s=5))
        finally:
            S.asyncio.sleep = orig
        self.assertEqual(len(calls), 3)

    def test_gives_up_after_budget(self):
        from mvp.sim_mcp import sessions as S
        blank = self._png(True)

        class Page:
            async def screenshot(self, **kw):
                return blank

        asyncio.run(S._wait_rendered(Page(), budget_s=0.01))
