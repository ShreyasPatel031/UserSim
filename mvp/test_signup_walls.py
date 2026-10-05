"""Signup walls: our alias/poll/timeout bugs, not the site's.

No network, no Browserbase, no Gmail. Pure helpers only.
"""

from __future__ import annotations

import os
import time
import unittest
from unittest import mock


class AliasBlockTests(unittest.TestCase):
    def test_plus_and_account_exists_rotate_domain_walls_do_not(self) -> None:
        from mvp.signup_inbox import can_rotate_alias, classify_alias_block

        self.assertEqual(classify_alias_block('{"code":"plus_addressing_not_allowed"}'), "plus")
        self.assertEqual(classify_alias_block("Plus addressing is not allowed"), "plus")
        self.assertEqual(
            classify_alias_block("There is already an account with this email address."),
            "exists",
        )
        self.assertEqual(classify_alias_block('{"code":"account_exists"}'), "exists")
        self.assertEqual(classify_alias_block("This email is already registered"), "exists")
        # Site walls and the ordinary "log in" link must not burn a new alias.
        for wall in (
            "please try again later",
            "Users from this domain are blocked.",
            "use a work email",
            "Already have an account? Log in",
            "too many requests",
            "the code has already been used",
        ):
            self.assertIsNone(classify_alias_block(wall), wall)
        self.assertTrue(can_rotate_alias("plus", 0))
        self.assertTrue(can_rotate_alias("exists", 1))
        self.assertFalse(can_rotate_alias("exists", 2))
        self.assertFalse(can_rotate_alias(None, 0))
        self.assertFalse(can_rotate_alias("plus", 2))

    def test_posthog_plus_sentence_rotates_generic_walls_do_not(self) -> None:
        from mvp.signup_inbox import classify_alias_block

        # Live PostHog copy, straight and curly apostrophes, and close variants.
        self.assertEqual(
            classify_alias_block(
                "Email addresses with a '+' aren't supported. Please use your primary email address."
            ),
            "plus",
        )
        self.assertEqual(
            classify_alias_block("Email addresses with a '+' aren\u2019t supported."),
            "plus",
        )
        self.assertEqual(classify_alias_block("+ is not supported"), "plus")
        self.assertEqual(classify_alias_block("plus signs aren't supported"), "plus")
        self.assertEqual(classify_alias_block("plus signs aren\u2019t supported"), "plus")
        # Bare "not supported" and site walls must not burn an alias.
        self.assertIsNone(classify_alias_block("not supported"))
        self.assertIsNone(classify_alias_block("please try again later"))
        self.assertIsNone(classify_alias_block("use a work email"))
        self.assertIsNone(classify_alias_block("Already have an account? Log in"))
        self.assertIsNone(classify_alias_block("Users from this domain are blocked."))

    def test_retry_cap_is_two_even_if_env_asks_for_more(self) -> None:
        from mvp.signup_inbox import alias_retry_limit

        with mock.patch.dict(os.environ, {"MVP_SIGNUP_ALIAS_RETRIES": "50"}):
            self.assertEqual(alias_retry_limit(), 2)
        with mock.patch.dict(os.environ, {"MVP_SIGNUP_ALIAS_RETRIES": "0"}):
            self.assertEqual(alias_retry_limit(), 0)

    def test_dotted_retry_drops_plus_and_does_not_reuse_dots(self) -> None:
        from mvp.signup_inbox import fresh_gmail_address

        path = "/tmp/usersim-signup-wall-variants.txt"
        try:
            os.remove(path)
        except OSError:
            pass
        with mock.patch.dict(os.environ, {"MVP_GMAIL_VARIANTS_FILE": path, "MVP_SIGNUP_EMAIL_DOTS": "1"}):
            first = fresh_gmail_address("usersimsignups@gmail.com", "posthog.com", "posthog", dotted=False)
            dotted = [
                fresh_gmail_address("usersimsignups@gmail.com", "posthog.com", "posthog", dotted=True)
                for _ in range(2)
            ]
        local, _, domain = first.partition("@")
        self.assertEqual(domain, "gmail.com")
        self.assertIn("+", local)
        self.assertEqual(local.split("+", 1)[0].replace(".", ""), "usersimsignups")
        self.assertEqual(len(set(dotted)), 2)
        for addr in dotted:
            self.assertNotIn("+", addr)
            self.assertEqual(addr.split("@")[0].replace(".", ""), "usersimsignups")


class InboxPollTests(unittest.TestCase):
    def test_rate_limit_backs_off_empty_inbox_does_not(self) -> None:
        from mvp.email_codes import _imap_rate_limited
        from mvp.signup_inbox import poll_sleep_s

        self.assertEqual(poll_sleep_s(None, 0), 2.5)
        self.assertEqual(poll_sleep_s(TimeoutError("timed out"), 4), 2.5)
        limited = RuntimeError("Too many simultaneous connections. Rate limit")
        self.assertTrue(_imap_rate_limited(limited))
        self.assertEqual(poll_sleep_s(limited, 0), 5.0)
        self.assertEqual(poll_sleep_s(limited, 3), 20.0)
        self.assertFalse(_imap_rate_limited(TimeoutError("socket timeout")))

    def test_dot_stripped_plus_alias_still_matches_and_bare_mailbox_does_not(self) -> None:
        from mvp.email_codes import _alias_match

        alias = "u.sersimsignups+posthoga1b2c3@gmail.com"
        with mock.patch.dict(os.environ, {"GMAIL_USER": "usersimsignups@gmail.com"}):
            # Gmail often removes dots but keeps the plus-tag.
            self.assertTrue(_alias_match("usersimsignups+posthoga1b2c3@gmail.com", alias))
            self.assertTrue(_alias_match(alias, alias))
            # The normalized mailbox is every alias at once: matching it would
            # hand one agent's code to all the others.
            self.assertFalse(_alias_match("usersimsignups@gmail.com", alias))
            self.assertFalse(_alias_match("usersimsignups@gmail.com", "u.sersimsignups@gmail.com"))
            # Original dotted recipient, which a dotted retry depends on.
            self.assertTrue(
                _alias_match(
                    "envelope-to: u.sersimsignups@gmail.com",
                    "u.sersimsignups@gmail.com",
                )
            )


class DeadlineTests(unittest.TestCase):
    def test_email_poll_does_not_force_a_wait_past_the_deadline(self) -> None:
        from mvp.signup_in_session import email_poll_slice_s, model_call_timeout_s, nav_timeout_ms

        now = time.time()
        self.assertIsNone(email_poll_slice_s(now + 10, now=now))
        self.assertIsNone(email_poll_slice_s(now + 19, now=now))
        self.assertAlmostEqual(email_poll_slice_s(now + 40, now=now), 28.0)
        self.assertEqual(email_poll_slice_s(now + 200, now=now), 90.0)
        # Old code: max(5, min(75, negative)) still blocked for 5s.
        self.assertIsNone(model_call_timeout_s(now + 6, now=now))
        self.assertEqual(model_call_timeout_s(now + 20, now=now), 15.0)
        self.assertEqual(model_call_timeout_s(None, now=now), 40.0)
        self.assertEqual(nav_timeout_ms(now + 100, now=now), 60000)
        self.assertEqual(nav_timeout_ms(now + 20, now=now), 15000)
        self.assertLess(30000, nav_timeout_ms(now + 100, now=now))

    def test_domain_block_still_matches_email_reject_pattern(self) -> None:
        from mvp.signup_in_session import _EMAIL_REJECT
        from mvp.signup_inbox import classify_alias_block

        body = '{"err":"Users from this domain are blocked.","ECODE":"DOM_001"}'
        self.assertIsNotNone(_EMAIL_REJECT.search(body))
        self.assertIsNone(classify_alias_block(body))


class VerifyStepTests(unittest.TestCase):
    def test_verify_step_after_submit_waits_on_the_inbox(self) -> None:
        from mvp.signup_in_session import awaiting_email_code

        signup = "https://statable.com/auth/signup"
        self.assertTrue(awaiting_email_code("https://statable.com/auth/verify", "", email_submitted=True))
        for body in (
            "Enter the code we sent to your email. Passcode from your email",
            "Check your inbox to continue.",
            "Too many requests. Please wait a moment.",
        ):
            self.assertTrue(awaiting_email_code(signup, body, email_submitted=True), body)

    def test_before_submit_and_ordinary_pages_do_not(self) -> None:
        from mvp.signup_in_session import awaiting_email_code

        self.assertFalse(awaiting_email_code("https://statable.com/auth/verify", "", email_submitted=False))
        self.assertFalse(
            awaiting_email_code("https://x.com/signup", "Check your inbox", email_submitted=False)
        )
        for url, body in (
            ("https://x.com/signup", "Create your account. Email. Password. Sign up"),
            ("https://x.com/signup", "We'll send you a verification code"),
            ("https://x.com/dashboard", "Welcome! Add your first website"),
            ("https://x.com/onboarding", "Enter the code we texted to your phone"),
        ):
            self.assertFalse(awaiting_email_code(url, body, email_submitted=True), body)


if __name__ == "__main__":
    unittest.main()
