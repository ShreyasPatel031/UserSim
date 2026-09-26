"""Signup-in-session helpers. No live browsers."""

from __future__ import annotations

import unittest


class SignupInSessionTests(unittest.TestCase):
    def test_start_urls_for_the_five_e2e_sites(self) -> None:
        from mvp.signup_in_session import start_url_for

        self.assertIn("linear.app/signup", start_url_for("https://linear.app"))
        self.assertIn("trello.com/signup", start_url_for("https://trello.com/login"))
        self.assertIn("asana.com/create-account", start_url_for("https://asana.com"))
        self.assertIn("miro.com/signup", start_url_for("https://miro.com"))
        self.assertIn("tldraw.com", start_url_for("https://www.tldraw.com/"))

    def test_public_result_strips_mailbox_from_steps(self) -> None:
        from mvp.signup_in_session import _public_result

        result = _public_result(
            ok=False,
            reason="timeout",
            email="person+tag@example.com",
            started=0,
            steps=["typed person+tag@example.com password=hunter2"],
            alias_tag="tag",
        )
        self.assertNotIn("person+tag", " ".join(result["steps"]))
        self.assertNotIn("hunter2", " ".join(result["steps"]))
        self.assertEqual(result["email"], "person+tag@example.com")
        self.assertNotIn("password", result)

    def test_workspace_requires_more_than_an_anonymous_canvas(self) -> None:
        from mvp.signup_in_session import _workspace_ready

        anon = {
            "href": "https://www.tldraw.com/",
            "body": "very good free whiteboard",
            "buttons": ["Sign in to share"],
        }
        self.assertFalse(_workspace_ready("tldraw.com", anon))
        signed = {
            "href": "https://www.tldraw.com/",
            "body": "Account menu Sign out",
            "buttons": ["Account"],
        }
        self.assertTrue(_workspace_ready("tldraw.com", signed))

    def test_field_kind_skips_oauth_looking_names(self) -> None:
        from mvp.signup_in_session import _field_kind

        self.assertEqual(_field_kind({"type": "email", "name": "email", "maxLength": 0}), "email")
        self.assertEqual(
            _field_kind({"type": "password", "name": "password", "maxLength": 0}),
            "password",
        )
        self.assertEqual(
            _field_kind({"type": "text", "name": "otp", "maxLength": 6, "placeholder": "code"}),
            "code",
        )


if __name__ == "__main__":
    unittest.main()
