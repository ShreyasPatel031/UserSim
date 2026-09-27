"""Unit tests for the in-run signup hook (no browser, no network)."""

from __future__ import annotations

import unittest

from mvp.a11y_agent import (
    _typed_item_visible,
    competitor_signup_timeout_s,
    signup_block_label,
    signup_hopeless_without_keys,
)
from mvp.signup_inbox import rank_links
from mvp.signup_in_session import _OAUTH, _fmt_elements, _match_option, _visible_elements


class SignupLabels(unittest.TestCase):
    """The main loop (grokbot/integration-local) detects walls with the model and
    auth_page(); these check the words the report uses for a failed signup."""

    def test_block_labels(self) -> None:
        self.assertEqual(signup_block_label("email_rejected"), "blocked at signup: throwaway email rejected")
        self.assertIn("captcha", signup_block_label("captcha_unsolved"))
        self.assertTrue(signup_block_label("timeout").startswith("signup did not finish"))

    def test_typed_title_visible_outside_field(self) -> None:
        read = {"text": "Issues  My first issue  Todo", "nodes": [{"role": "textbox", "value": ""}]}
        self.assertTrue(_typed_item_visible(["My first issue"], read))
        open_editor = {"text": "My first issue", "nodes": [{"role": "textbox", "value": "My first issue"}]}
        self.assertFalse(_typed_item_visible(["My first issue"], open_editor))


class SignupHelpers(unittest.TestCase):
    def test_oauth_buttons_hidden(self) -> None:
        snap = {"elements": [
            {"i": 0, "role": "button", "name": "Continue with Google"},
            {"i": 1, "role": "button", "name": "Continue with email"},
            {"i": 2, "role": "button", "name": "Sign up with Microsoft"},
            {"i": 3, "role": "textbox", "name": "Email"},
        ]}
        names = [e["name"] for e in _visible_elements(snap)]
        self.assertEqual(names, ["Continue with email", "Email"])
        self.assertTrue(_OAUTH.search("SAML SSO"))

    def test_rank_links_prefers_verify(self) -> None:
        links = ["https://linear.app", "https://twitter.com/linear",
                 "https://linear.app/auth/email/x@y.com/abcdefghijklmnop"]
        self.assertEqual(rank_links(links, "linear.app")[0], links[2])



class SignupHopeless(unittest.TestCase):
    def test_every_site_hopeless_without_gmail(self) -> None:
        from unittest import mock

        with mock.patch("mvp.signup_inbox.gmail_available", return_value=False):
            for url in ("https://trello.com/signup", "https://linear.app/", "https://asana.com/"):
                reason = signup_hopeless_without_keys(url)
                self.assertIn("gmail_inbox_missing", reason or "", url)

    def test_create_inbox_gmail_only_no_fallback(self) -> None:
        import os
        from unittest import mock

        import mvp.signup_inbox as si

        self.assertFalse(hasattr(si, "MailTmInbox"))
        self.assertFalse(hasattr(si, "GuerrillaInbox"))
        with mock.patch.object(si, "gmail_available", return_value=False):
            with self.assertRaises(si.GmailInboxMissing):
                si.create_inbox("clickup.com", "clickup")
        with mock.patch.dict(os.environ, {"MVP_SIGNUP_INBOX": "mailtm"}):
            with self.assertRaises(si.GmailInboxMissing):
                si.create_inbox("clickup.com", "clickup")

    def test_create_inbox_gmail_alias_fresh_per_signup(self) -> None:
        import os
        from unittest import mock

        import mvp.signup_inbox as si

        env = {"GMAIL_USER": "someone@gmail.com", "GMAIL_APP_PASSWORD": "x" * 16}
        with mock.patch.dict(os.environ, env):
            os.environ.pop("MVP_SIGNUP_INBOX", None)
            a = si.create_inbox("clickup.com", "clickup")
            b = si.create_inbox("clickup.com", "clickup")
        self.assertEqual(a.backend, "gmail")
        # Dots spread through the real local part (same Gmail inbox) plus a fresh +tag.
        local = a.address.split("@", 1)[0]
        self.assertEqual(local.split("+", 1)[0].replace(".", ""), "someone", a.address)
        self.assertIn(".", local.split("+", 1)[0])
        self.assertIn("+clickup", local)
        self.assertTrue(a.address.endswith("@gmail.com"), a.address)
        self.assertNotEqual(a.address, b.address)

    def test_miro_hopeless_without_capsolver(self) -> None:
        import os
        os.environ.pop("CAPSOLVER_API_KEY", None)
        os.environ.pop("MVP_CAPTCHA_API_KEY", None)
        reason = signup_hopeless_without_keys("https://miro.com/signup/")
        self.assertIsNotNone(reason)
        self.assertIn("captcha", reason or "")

    def test_linear_not_hopeless(self) -> None:
        from unittest import mock

        with mock.patch("mvp.signup_inbox.gmail_available", return_value=True):
            reason = signup_hopeless_without_keys("https://linear.app/")
        self.assertIsNone(reason)

    def test_competitor_timeout_default(self) -> None:
        import os
        os.environ.pop("MVP_SIGNUP_COMPETITOR_TIMEOUT_S", None)
        self.assertEqual(competitor_signup_timeout_s(), 150.0)

class ClearCaptchaNoFalseOk(unittest.TestCase):
    """Calendly: reCAPTCHA Enterprise v2 image challenge open, stray token filled."""

    def test_recaptcha_page_is_not_cleared_by_turnstile_click_or_token(self) -> None:
        import asyncio
        import os
        from unittest import mock

        import mvp.captcha as cap
        import mvp.signup_in_session as sis

        class _Loc:
            first = property(lambda self: self)

            async def get_attribute(self, name, timeout=0):
                return "false"

        class _Frame:
            url = "https://www.recaptcha.net/recaptcha/enterprise/anchor?k=x"

            def locator(self, sel):
                return _Loc()

        class _Page:
            frames = [_Frame()]

            async def wait_for_timeout(self, ms):
                return None

            async def evaluate(self, js):
                return True  # captcha frame still visible

        async def _yes(*a, **k):
            return True

        async def _audio_fail(page):
            return {"ok": False, "method": "audio"}

        snap = {"captcha": "https://www.recaptcha.net/recaptcha/enterprise/anchor?k=x"}
        with mock.patch.object(cap, "_click_recaptcha_checkbox", _yes), \
                mock.patch.object(cap, "_recaptcha_solved", _yes), \
                mock.patch.object(cap, "_try_click_cloudflare_checkbox", _yes), \
                mock.patch("mvp.signup_captcha_audio.solve_recaptcha_audio", _audio_fail), \
                mock.patch.dict(os.environ, {"CAPSOLVER_API_KEY": "", "MVP_CAPTCHA_API_KEY": ""}):
            res = asyncio.run(sis._clear_captcha(_Page(), snap, {"usd": 0.0, "calls": 0, "site": "calendly.com"}))
        self.assertFalse(res["ok"], res)
        self.assertEqual(res["method"], "no_capsolver_key")



class ApiRejectPatternTests(unittest.TestCase):
    def test_clickup_domain_block_matches_email_reject(self) -> None:
        from mvp.signup_in_session import _EMAIL_REJECT

        body = '{"err":"Users from this domain are blocked.","ECODE":"DOM_001"}'
        self.assertIsNotNone(_EMAIL_REJECT.search(body))


class GmailAliasFreshTests(unittest.TestCase):
    def test_each_gmail_inbox_gets_a_new_alias(self) -> None:
        from unittest.mock import patch

        from mvp.signup_inbox import GmailAliasInbox

        with patch("mvp.email_codes._imap_creds", return_value=("base@gmail.com", "x")):
            a = GmailAliasInbox("notion.so", "notion").address
            b = GmailAliasInbox("notion.so", "notion").address
        self.assertNotEqual(a, b)
        self.assertTrue(a.endswith("@gmail.com") and "notion" in a)


class SelectOptionTests(unittest.TestCase):
    """kolanut.ai onboarding: 'Team size' options use en dashes; the model wrote
    '1-10 employees', select_option(label=...) timed out every time, Next stayed
    disabled and signup ended stuck/timeout on engagement.kolanut.ai/onboarding."""

    OPTS = [{"text": "Select team size", "value": ""}] + [
        {"text": t, "value": v}
        for t, v in (
            ("1\u201310 employees", "1-10"),
            ("11\u201350 employees", "11-50"),
            ("201\u20131,000 employees", "201-1000"),
            ("1,000+ employees", "1000+"),
        )
    ]

    def test_ascii_dash_matches_en_dash_option(self) -> None:
        self.assertEqual(_match_option("1-10 employees", self.OPTS), 1)
        self.assertEqual(_match_option("11\u201350 employees", self.OPTS), 2)
        self.assertEqual(_match_option("201-1000 employees", self.OPTS), 3)
        self.assertEqual(_match_option("1,000+ employees", self.OPTS), 4)

    def test_empty_value_picks_first_real_option_not_placeholder(self) -> None:
        self.assertEqual(_match_option("", self.OPTS), 1)

    def test_no_match_returns_none(self) -> None:
        self.assertIsNone(_match_option("Enterprise tier", self.OPTS))

    def test_model_sees_real_characters(self) -> None:
        out = _fmt_elements([{"i": 1, "role": "select", "name": "Team size *",
                              "options": "Select team size | 1\u201310 employees"}])
        self.assertIn("1\u201310 employees", out)
        self.assertNotIn("\\u2013", out)


if __name__ == "__main__":
    unittest.main()


def test_onboarding_path_only_blocks_leading_setup_steps():
    from mvp.signup_in_session import onboarding_blocks

    # kolanut: a checklist page inside the app (full sidebar) is the app.
    assert not onboarding_blocks("/dashboard/workspace/get-started")
    assert not onboarding_blocks("/dashboard/workspace/home")
    # Setup wizards before the app still block.
    assert onboarding_blocks("/onboarding")
    assert onboarding_blocks("/onboarding/profile")
    assert onboarding_blocks("/welcome")
    assert onboarding_blocks("/team/join")
    assert onboarding_blocks("/signup")


class GmailVariantsAndGrace(unittest.TestCase):
    def test_dot_variant_same_mailbox_and_varies(self) -> None:
        from mvp.identity import email_for_host, gmail_dot_variant

        seen = {gmail_dot_variant("shreyashfs") for _ in range(40)}
        self.assertGreater(len(seen), 10)
        for v in seen:
            self.assertEqual(v.replace(".", ""), "shreyashfs")
            self.assertFalse(v.startswith(".") or v.endswith(".") or ".." in v)
            self.assertLessEqual(v.count("."), 3)
        self.assertNotIn(gmail_dot_variant("shreyashfs", avoid=seen - {"s.hreyashfs"}) , seen - {"s.hreyashfs"})
        # Dotted aliases stay in the same Gmail mailbox (no ".tag" suffix).
        addr = email_for_host("shreyashfs@gmail.com", "ticktick.com", tag="x1", force_dotted=True)
        self.assertEqual(addr.split("@")[0].replace(".", ""), "shreyashfs")

    def test_alias_match_dot_variant_needs_exact_address(self) -> None:
        import os
        from unittest import mock

        from mvp.email_codes import _alias_match

        with mock.patch.dict(os.environ, {"GMAIL_USER": "shreyashfs@gmail.com"}):
            self.assertTrue(_alias_match("s.hrey.ashfs+zo1a2b3c@gmail.com", "s.hrey.ashfs+zo1a2b3c@gmail.com"))
            self.assertFalse(_alias_match("shreyashfs+n8n99@gmail.com", "s.hrey.ashfs+zo1a2b3c@gmail.com"))
            self.assertFalse(_alias_match("shreyashfs@gmail.com", "s.hreyashfs@gmail.com"))
            self.assertTrue(_alias_match("s.hreyashfs@gmail.com", "s.hreyashfs@gmail.com"))

    def test_captcha_grace_extends_deadline_once(self) -> None:
        import time

        from mvp.signup_in_session import _grant_captcha_grace

        spend = {"deadline": time.time() + 10, "site": "zapier.com", "grace_s": 60}
        before = spend["deadline"]
        _grant_captcha_grace(spend)
        _grant_captcha_grace(spend)
        self.assertAlmostEqual(spend["deadline"] - before, 60, delta=0.01)

    def test_host_gap(self) -> None:
        import os
        from unittest import mock

        from mvp.a11y_agent import signup_host_gap_s

        self.assertEqual(signup_host_gap_s("zo.computer"), 6.0)
        self.assertEqual(signup_host_gap_s("zapier.com"), 0.0)
        with mock.patch.dict(os.environ, {"MVP_SIGNUP_HOST_GAP_S": "zapier.com=2,zo.computer=9"}):
            self.assertEqual(signup_host_gap_s("www.zapier.com"), 2.0)
            self.assertEqual(signup_host_gap_s("zo.computer"), 9.0)

    def test_step_model_timeout(self) -> None:
        from mvp.a11y_agent import _step_model_timeout

        self.assertLess(_step_model_timeout(False, 0) * 2, 10.0)
        self.assertEqual(_step_model_timeout(True, 0), 20.0)


class SurveySkip(unittest.TestCase):
    def test_n8n_survey_skip_found(self) -> None:
        from mvp.signup_in_session import survey_skip_control

        snap = {
            "url": "https://app.n8n.cloud/account/setup",
            "body": "Customize n8n to you. What best describes your company?",
            "elements": [
                {"i": 0, "role": "combobox", "name": "Company type"},
                {"i": 1, "role": "button", "name": "Get started"},
                {"i": 2, "role": "button", "name": "Skip"},
            ],
        }
        self.assertEqual(survey_skip_control(snap)["i"], 2)

    def test_no_skip_on_signup_form(self) -> None:
        from mvp.signup_in_session import survey_skip_control

        snap = {"url": "https://zapier.com/sign-up", "body": "Create your account",
                "elements": [{"i": 0, "role": "button", "name": "Skip"}]}
        self.assertIsNone(survey_skip_control(snap))


class SitekeyFromFrames(unittest.TestCase):
    def test_recaptcha_anchor(self) -> None:
        from mvp.signup_in_session import sitekey_from_frames

        got = sitekey_from_frames([
            "https://www.google.com/recaptcha/api2/anchor?ar=1&k=6LdABC123&co=aHR0cHM6&size=normal",
        ])
        self.assertEqual(got, {"sitekey": "6LdABC123", "type": "recaptcha"})
        self.assertIsNone(sitekey_from_frames(["https://www.google.com/recaptcha/api2/anchor?k=x&size=invisible"]))
