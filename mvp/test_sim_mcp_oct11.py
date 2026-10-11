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
            sub = fresh_gmail_address("usersim.signups@gmail.com", "app.chatwoot.com", "app")
            other = fresh_gmail_address("usersim.signups@gmail.com", "smartlook.com", "smartlook")
        self.assertEqual(plain, "usersim.signups@gmail.com")
        self.assertEqual(sub, "usersim.signups@gmail.com")
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


class DropdownSnapTests(unittest.TestCase):
    def test_dropdowns_listed_with_coordinates(self):
        import shutil

        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        if not chrome:
            self.skipTest("no chrome")
        from mvp.sim_mcp.sessions import _DROPDOWNS_JS

        body = ("<input placeholder='Full name' style='display:block;width:300px;height:40px'>"
                "<div role='combobox' aria-label='Your role' style='width:300px;height:40px;margin-top:20px'>Your role*</div>"
                "<div aria-haspopup='listbox' style='width:300px;height:40px;margin-top:20px'>Organization size*</div>")

        async def run():
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                b = await p.chromium.launch(headless=True, executable_path=chrome)
                pg = await b.new_page()
                await pg.set_content(body)
                out = await pg.evaluate(_DROPDOWNS_JS)
                await b.close()
                return out

        out = asyncio.run(run())
        self.assertEqual([o["label"] for o in out], ["Your role", "Organization size*"])
        self.assertLess(out[0]["y"], out[1]["y"])


class NewlyVisibleListTests(unittest.TestCase):
    def test_unclassed_list_found_by_what_appeared(self):
        """Pingdom/Smartlook-style list: plain divs with no option role or class, shown on click."""
        import shutil

        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        if not chrome:
            self.skipTest("no chrome")
        from mvp.sim_mcp import sessions as S

        body = ("<div id=box style='width:300px;height:40px;border:1px solid #888;margin:40px'>Select state</div>"
                "<div id=lst style='display:none'><div><div>Alabama</div></div><div><div>Texas</div></div><div><div>Utah</div></div></div>"
                "<script>box.onclick=()=>{lst.style.display='block'};"
                "lst.querySelectorAll('div div').forEach(d=>d.onclick=()=>{box.textContent=d.textContent;lst.style.display='none'})</script>")

        async def run(want):
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                b = await p.chromium.launch(headless=True, executable_path=chrome)
                pg = await b.new_page()
                await pg.set_content(body)
                err = None
                try:
                    await S._execute(pg, {"type": "select", "x": 190, "y": 60, "option": want})
                except Exception as exc:  # noqa: BLE001
                    err = str(exc)
                txt = await pg.inner_text("#box")
                await b.close()
                return txt, err

        txt, err = asyncio.run(run("Texas"))
        self.assertEqual(txt, "Texas", err)
        txt, err = asyncio.run(run("Nevada"))
        self.assertIn("Alabama", err or "")


class UnrecognisedBoxTests(unittest.TestCase):
    """Oct 11 Pingdom 'State': a plain styled div box; the model aimed at its bottom edge (just outside)."""

    def _run(self, body, action, sel):
        import shutil

        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        if not chrome:
            self.skipTest("no chrome")
        from mvp.sim_mcp import sessions as S

        async def go():
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                b = await p.chromium.launch(headless=True, executable_path=chrome)
                pg = await b.new_page()
                await pg.set_content(body)
                err = None
                try:
                    await S._execute(pg, action)
                except Exception as exc:  # noqa: BLE001
                    err = str(exc)
                v = await pg.evaluate(f"() => {{ const e = document.querySelector({sel!r}); return e.value ?? e.textContent; }}")
                await b.close()
                return v, err

        return asyncio.run(go())

    def test_click_just_below_box_snaps_to_it(self):
        body = ("<div id=box style='width:300px;height:30px;border:1px solid #888;margin:40px'>Select state</div>"
                "<div id=lst style='display:none'><div><span>Alabama</span></div><div><span>Texas</span></div></div>"
                "<script>box.onclick=()=>{lst.style.display='block'};"
                "lst.querySelectorAll('span').forEach(d=>d.onclick=()=>{box.textContent=d.textContent;lst.style.display='none'})</script>")
        v, err = self._run(body, {"type": "select", "x": 190, "y": 84, "option": "Texas"}, "#box")
        self.assertEqual(v, "Texas", err)

    def test_searchable_box_typed_to_filter(self):
        states = ["Alabama", "Alaska", "Texas", "Utah"]
        body = ("<input id=q placeholder='Select state' style='width:300px;height:30px;margin:40px'>"
                "<div id=lst></div><script>q.oninput=()=>{lst.innerHTML='';"
                f"{states!r}.filter(s=>s.toLowerCase().startsWith(q.value.toLowerCase())).forEach(s=>{{"
                "const d=document.createElement('div');d.textContent=s;d.onclick=()=>{q.value=s;lst.innerHTML=''};lst.appendChild(d)})}</script>")
        v, err = self._run(body, {"type": "select", "x": 190, "y": 60, "option": "Texas"}, "#q")
        self.assertEqual(v, "Texas", err)


    def test_box_inside_iframe(self):
        inner = ("<div id=box style='width:300px;height:30px;border:1px solid #888;margin:20px'>Select state</div>"
                 "<div id=lst style='display:none'><div>Alabama</div><div>Texas</div></div>"
                 "<script>box.onclick=()=>{lst.style.display='block'};"
                 "lst.querySelectorAll('div').forEach(d=>d.onclick=()=>{box.textContent=d.textContent;"
                 "parent.document.getElementById('out').textContent=d.textContent;lst.style.display='none'})</script>")
        body = ("<div style='height:100px'>header</div><iframe id=f style='width:600px;height:300px;border:0' srcdoc=\"" + inner.replace('"', '&quot;') + "\"></iframe>"
                "<div id=out>Select state</div>")
        v, err = self._run(body, {"type": "select", "x": 170, "y": 136, "option": "Texas"}, "#out")
        self.assertEqual(v, "Texas", err)


class OptionMatchTests(unittest.TestCase):
    """Oct 11 stretch 3: fuzzy option match (Smartlook) and scrolled-out options (Pingdom)."""

    def test_scores_and_threshold(self):
        from mvp.sim_mcp import sessions as S

        self.assertGreaterEqual(S._option_score("Product Manager", "Product Management"), S.OPTION_MATCH_MIN)
        self.assertLess(S._option_score("Product Manager", "Project Management"), S.OPTION_MATCH_MIN)
        self.assertLess(S._option_score("Alaska", "Alabama"), S.OPTION_MATCH_MIN)
        best = S._best_option("Product Manager", [{"t": "UX & Design"}, {"t": "Product Management"}, {"t": "Engineering"}])
        self.assertEqual(best["t"], "Product Management")
        self.assertIsNone(S._best_option("Nevada", [{"t": "Alabama"}, {"t": "Texas"}]))
        self.assertEqual(S._nearest_first("Product Manager", ["Engineering", "Project Management", "UX"])[0], "Project Management")

    def _run(self, body, action, sel):
        return UnrecognisedBoxTests._run(self, body, action, sel)

    def test_fuzzy_pick_in_open_list(self):
        body = ("<div id=box style='width:300px;height:30px;border:1px solid #888;margin:40px'>Your role</div>"
                "<div id=lst style='display:none'><div>UX &amp; Design</div><div>Product Management</div><div>Engineering</div></div>"
                "<script>box.onclick=()=>{lst.style.display='block'};"
                "lst.querySelectorAll('div').forEach(d=>d.onclick=()=>{box.textContent=d.textContent;lst.style.display='none'})</script>")
        v, err = self._run(body, {"type": "select", "x": 190, "y": 56, "option": "Product Manager"}, "#box")
        self.assertEqual(v, "Product Management", err)
        v, err = self._run(body, {"type": "select", "x": 190, "y": 56, "option": "Sales Lead"}, "#box")
        self.assertIn("nearest first", err or "")

    def test_option_below_visible_part_of_scrolled_list(self):
        states = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware",
                  "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
                  "Louisiana", "Maine", "Maryland", "Texas", "Utah", "Vermont", "Virginia", "Washington"]
        items = "".join(f"<div class=it style='height:24px'>{s}</div>" for s in states)
        body = ("<div id=box style='width:300px;height:30px;border:1px solid #888;margin:40px'>Select state</div>"
                f"<div id=lst style='display:none;height:120px;overflow-y:auto;width:300px'>{items}</div>"
                "<script>box.onclick=()=>{lst.style.display='block'};"
                "lst.querySelectorAll('.it').forEach(d=>d.onclick=()=>{box.textContent=d.textContent;lst.style.display='none'})</script>")
        v, err = self._run(body, {"type": "select", "x": 190, "y": 56, "option": "Texas"}, "#box")
        self.assertEqual(v, "Texas", err)


class NewsletterChromeLinkTests(unittest.TestCase):
    """Loggly: the welcome mail's "View Online" link (Marketo /v/ path) counted as verification."""

    def test_view_online_is_not_verification(self):
        from mvp.signup_inbox import verification_link

        url = "https://sw1.solarwinds.com/v/NTY0LVZGUi0wMDgAAAGkyhLCV7abaLkQ5rAeNpNmavdshD8rdWILrTv3G"
        self.assertFalse(verification_link(url, "View Online"))
        self.assertFalse(verification_link("https://x.example/confirm?u=1", "Unsubscribe"))
        self.assertTrue(verification_link("https://app.example.com/verify?t=abc", "Verify my email"))
        self.assertTrue(verification_link("https://click.example/abc", "Confirm my email"))

    def test_view_online_ranked_last(self):
        from mvp.signup_inbox import rank_links

        a = "https://sw1.solarwinds.com/v/" + "x" * 60
        b = "https://www.loggly.com/welcome"
        ranked = rank_links([a, b], "loggly.com", {a: "View Online", b: "here"})
        self.assertEqual(ranked[0], b)
