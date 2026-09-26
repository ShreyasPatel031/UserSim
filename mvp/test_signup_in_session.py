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
    def test_trello_hopeless_without_gmail(self) -> None:
        import os
        os.environ.pop("GMAIL_USER", None)
        os.environ.pop("GMAIL_APP_PASSWORD", None)
        os.environ.pop("MVP_SIGNUP_INBOX", None)
        reason = signup_hopeless_without_keys("https://trello.com/signup")
        self.assertIsNotNone(reason)
        self.assertIn("email_rejected", reason or "")

    def test_miro_hopeless_without_capsolver(self) -> None:
        import os
        os.environ.pop("CAPSOLVER_API_KEY", None)
        os.environ.pop("MVP_CAPTCHA_API_KEY", None)
        reason = signup_hopeless_without_keys("https://miro.com/signup/")
        self.assertIsNotNone(reason)
        self.assertIn("captcha", reason or "")

    def test_linear_not_hopeless(self) -> None:
        reason = signup_hopeless_without_keys("https://linear.app/")
        self.assertIsNone(reason)

    def test_competitor_timeout_default(self) -> None:
        import os
        os.environ.pop("MVP_SIGNUP_COMPETITOR_TIMEOUT_S", None)
        self.assertEqual(competitor_signup_timeout_s(), 40.0)

if __name__ == "__main__":
    unittest.main()
