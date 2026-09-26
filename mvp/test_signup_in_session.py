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
from mvp.signup_in_session import _OAUTH, _visible_elements


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
        self.assertTrue(a.address.startswith("someone+clickup") and a.address.endswith("@gmail.com"), a.address)
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
        self.assertEqual(competitor_signup_timeout_s(), 40.0)

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

if __name__ == "__main__":
    unittest.main()


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
