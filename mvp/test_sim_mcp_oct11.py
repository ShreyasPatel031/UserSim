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


    def test_aimed_one_field_off_tries_the_neighbour_box(self):
        """Pingdom retest: the State point hit Time Zone (a list with nothing like 'Texas')."""
        body = ("<style>.b{width:300px;height:30px;border:1px solid #888;margin:10px 40px}.l{display:none;position:absolute;left:420px;top:20px}</style>"
                "<div id=st class=b>Select state</div><div id=tz class=b>GMT-5 Eastern</div>"
                "<div id=sl class=l><div>Alabama</div><div>Texas</div></div>"
                "<div id=tl class=l><div>GMT-8 Pacific</div><div>GMT-4:30 Caracas</div></div>"
                "<script>st.onclick=()=>{sl.style.display='block'};tz.onclick=()=>{tl.style.display='block'};"
                "document.onkeydown=e=>{if(e.key==='Escape'){sl.style.display='none';tl.style.display='none'}};"
                "sl.querySelectorAll('div').forEach(d=>d.onclick=()=>{st.textContent=d.textContent;sl.style.display='none'});"
                "tl.querySelectorAll('div').forEach(d=>d.onclick=()=>{tz.textContent=d.textContent;tl.style.display='none'})</script>")
        v, err = self._run(body, {"type": "select", "x": 190, "y": 70, "option": "Texas"}, "#st")
        self.assertEqual(v, "Texas", err)


    def test_no_typing_into_another_focused_field(self):
        """Smartlook: the box's mousedown kept focus in Full name; the option text was typed into it."""
        body = ("<input id=nm value='Sam Rivera' style='width:300px;height:30px;margin:10px 40px'>"
                "<div id=box style='width:300px;height:30px;border:1px solid #888;margin:10px 40px'>Your role</div>"
                "<div id=lst style='display:none'><div>UX &amp; Design</div><div>Product Management</div></div>"
                "<script>box.onmousedown=e=>e.preventDefault();box.onclick=()=>{lst.style.display='block'};"
                "lst.querySelectorAll('div').forEach(d=>{d.onmousedown=e=>e.preventDefault();d.onclick=()=>{box.textContent=d.textContent;lst.style.display='none'}});"
                "nm.focus()</script>")
        v, err = self._run(body, {"type": "select", "x": 190, "y": 75, "option": "Sales"}, "#nm")
        self.assertEqual(v, "Sam Rivera", err)
        v, err = self._run(body, {"type": "select", "x": 190, "y": 75, "option": "Product Manager"}, "#box")
        self.assertEqual(v, "Product Management", err)


    def test_named_field_wins_over_the_point(self):
        """Smartlook: the model's point opened Country/role; select(field='Organization size') must open that box."""
        mk = lambda i, lab: (f"<div id=b{i} role=combobox aria-label='{lab}' class=b>{lab}</div>")
        body = ("<style>.b{width:300px;height:30px;border:1px solid #888;margin:10px 40px}.l{display:none;position:absolute;left:420px;top:20px}</style>"
                + mk(1, "Your role*") + mk(2, "Organization size*") + mk(3, "Country*") +
                "<div id=l1 class=l><div>Engineering</div><div>Product Management</div></div>"
                "<div id=l2 class=l><div>Self-employed</div><div>1 - 10 employees</div></div>"
                "<div id=l3 class=l><div>Romania</div><div>Panama</div></div>"
                "<script>[1,2,3].forEach(i=>{const b=document.getElementById('b'+i),l=document.getElementById('l'+i);"
                "b.onclick=()=>{l.style.display='block'};l.querySelectorAll('div').forEach(d=>d.onclick=()=>{b.textContent=d.textContent;l.style.display='none'})});"
                "document.onkeydown=e=>{if(e.key==='Escape')document.querySelectorAll('.l').forEach(l=>l.style.display='none')}</script>")
        v, err = self._run(body, {"type": "select", "x": 190, "y": 130, "option": "1 - 10 employees", "field": "Organization size"}, "#b2")
        self.assertEqual(v, "1 - 10 employees", err)

    def test_already_open_list_is_not_toggled_closed(self):
        """Smartlook retest: the org-size list was already open; clicking its box closed it, then role opened."""
        mk = lambda i, lab: (f"<div id=b{i} role=combobox aria-label='{lab}' class=b>{lab}</div>")
        body = ("<style>.b{width:300px;height:30px;border:1px solid #888;margin:10px 40px}.l{display:none;position:absolute;left:420px;top:20px}</style>"
                + mk(1, "Your role*") + mk(2, "Organization size*") +
                "<div id=l1 class=l><div>Engineering</div><div>Product Management</div></div>"
                "<div id=l2 class=l><div>Self-employed</div><div>1 - 10 employees</div></div>"
                "<script>[1,2].forEach(i=>{const b=document.getElementById('b'+i),l=document.getElementById('l'+i);"
                "b.onclick=()=>{const o=l.style.display==='block';document.querySelectorAll('.l').forEach(x=>x.style.display='none');l.style.display=o?'none':'block'};"
                "l.querySelectorAll('div').forEach(d=>d.onclick=()=>{b.textContent=d.textContent;l.style.display='none'})});"
                "document.getElementById('l2').style.display='block'</script>")
        v, err = self._run(body, {"type": "select", "x": 190, "y": 80, "option": "1 - 10 employees", "field": "Organization size"}, "#b2")
        self.assertEqual(v, "1 - 10 employees", err)


class IframeFieldsTests(unittest.TestCase):
    """Oct 11 Pingdom: controls inside the onboarding iframe were never listed, so the model guessed (off-frame)."""

    def test_iframe_controls_listed_in_page_coordinates(self):
        import shutil

        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        if not chrome:
            self.skipTest("no chrome")
        from mvp.sim_mcp import sessions as S

        inner = "<div style='height:900px'>form</div><button id=go style='width:200px;height:40px'>Start using Pingdom</button>"
        body = ("<div style='height:60px'>top bar</div><iframe style='width:800px;height:1000px;border:0' srcdoc=\""
                + inner + "\"></iframe>")

        async def go():
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                b = await p.chromium.launch(headless=True, executable_path=chrome)
                pg = await b.new_page(viewport={"width": 1280, "height": 800})
                await pg.set_content(body)
                await asyncio.sleep(0.3)
                await pg.mouse.wheel(0, 400)
                await asyncio.sleep(0.3)
                rows = await S._fields(pg)
                btn = next((r for r in rows if r.get("label") == "Start using Pingdom"), None)
                hit = await pg.evaluate("([x, y]) => { const e = document.elementFromPoint(x, y); return e && e.tagName; }",
                                        [btn["x"], btn["y"]]) if btn else None
                await b.close()
                return btn, hit

        btn, hit = asyncio.run(go())
        self.assertIsNotNone(btn)
        self.assertTrue(0 <= btn["y"] < 800, btn)
        self.assertEqual(hit, "IFRAME")


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


class InPageJumpTests(unittest.TestCase):
    """Oct 11 OpenReplay: an in-page 'Start 7-day trial' anchor (#dedicated) misled the model."""

    def test_fragment_only_change_is_an_in_page_jump(self):
        from mvp.sim_mcp import sessions as S

        self.assertTrue(S._in_page_jump("https://openreplay.com/pricing/", "https://openreplay.com/pricing/#dedicated"))
        self.assertTrue(S._in_page_jump("https://x.io/p#a", "https://x.io/p#b"))
        self.assertFalse(S._in_page_jump("https://openreplay.com/pricing/", "https://app.openreplay.com/signup"))
        self.assertFalse(S._in_page_jump("https://x.io/p#a", "https://x.io/p"))
        self.assertFalse(S._in_page_jump("https://x.io/p", "https://x.io/p"))
        self.assertIn("#dedicated", S.IN_PAGE_JUMP_NOTE.format(frag="dedicated"))


class HtmlOnlyCodeMailTests(unittest.TestCase):
    """Oct 11 Checkly: an HTML-only verification-code mail ('This email has no text version')."""

    def test_code_read_from_html_when_text_is_a_stub(self):
        from mvp.signup_inbox import _text_or_html, find_code

        html = "<html><body><p>Your Checkly verification code is</p><h1>482913</h1><p>It expires in 10 minutes.</p></body></html>"
        text = _text_or_html("This email has no text version", html)
        self.assertEqual(find_code("Checkly Verification Code", text), "482913")
        long_text = "Hello! Your code is 123456. " + "x" * 100
        self.assertEqual(_text_or_html(long_text, html), long_text)
