"""Browserbase session-create retries stay off the 5s screenshot clock."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch


class FlagLadderTests(unittest.TestCase):
    def test_signup_ladder_tries_solve_without_proxies(self) -> None:
        from capability.browserbase_client import session_flag_attempts

        attempts = session_flag_attempts(
            proxies=True, solve_captchas=True, advanced_stealth=False
        )
        self.assertEqual(
            attempts[0],
            {"proxies": True, "solve_captchas": True, "advanced_stealth": False},
        )
        self.assertEqual(
            attempts[1],
            {"proxies": False, "solve_captchas": True, "advanced_stealth": False},
        )
        self.assertEqual(attempts[-1]["proxies"], False)
        self.assertFalse(attempts[-1]["solve_captchas"])
        self.assertFalse(any(a["advanced_stealth"] for a in attempts))


class BackoffTests(unittest.TestCase):
    def test_timeout_backoff_is_short(self) -> None:
        from capability.browserbase_client import _create_backoff_s

        for attempt in range(4):
            delay = _create_backoff_s(attempt, TimeoutError("timed out after 18s"))
            self.assertGreater(delay, 0.2)
            self.assertLess(delay, 4.0)

    def test_rate_limit_backoff_is_jittered_and_capped(self) -> None:
        from capability.browserbase_client import _create_backoff_s

        os.environ["BROWSERBASE_429_BACKOFF_S"] = "1.5"
        os.environ["BROWSERBASE_429_BACKOFF_CAP_S"] = "8"
        samples = [
            _create_backoff_s(3, RuntimeError("429 too many requests"))
            for _ in range(12)
        ]
        self.assertGreater(max(samples) - min(samples), 0.05)
        for delay in samples:
            # cap plus the jitter term (35% of the capped delay)
            self.assertLess(delay, 8 * 1.35 + 0.2)
            self.assertGreater(delay, 1.0)


class CreateRetryTests(unittest.TestCase):
    def _session(self, sid: str) -> MagicMock:
        m = MagicMock()
        m.id = sid
        m.connect_url = f"wss://example/{sid}"
        return m

    def test_timeout_then_success_retries(self) -> None:
        from capability.browserbase_client import create_session

        calls = {"n": 0}

        def _create(**_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("Browserbase session create timed out after 18s")
            return self._session("ok-1")

        client = MagicMock()
        client.sessions.create.side_effect = _create
        with (
            patch("capability.browserbase_client.browserbase_api_key", return_value="k"),
            patch("capability.browserbase_client.browserbase_project_id", return_value="p"),
            patch("capability.browserbase_client.Browserbase", return_value=client),
            patch("capability.browserbase_client.time.sleep"),
        ):
            session = create_session(proxies=False, owner="e2e", study_id="s")
        self.assertEqual(session.id, "ok-1")
        self.assertGreaterEqual(calls["n"], 2)

    def test_non_retryable_does_not_loop(self) -> None:
        from capability.browserbase_client import BrowserbaseRateLimitError, create_session

        calls = {"n": 0}

        def _create(**_kwargs):
            calls["n"] += 1
            raise RuntimeError("invalid request payload")

        client = MagicMock()
        client.sessions.create.side_effect = _create
        with (
            patch("capability.browserbase_client.browserbase_api_key", return_value="k"),
            patch("capability.browserbase_client.browserbase_project_id", return_value="p"),
            patch("capability.browserbase_client.Browserbase", return_value=client),
            patch("capability.browserbase_client.time.sleep"),
        ):
            with self.assertRaises(BrowserbaseRateLimitError):
                create_session(proxies=False, owner="e2e", study_id="s")
        self.assertEqual(calls["n"], 1)

    def test_abandoned_timeout_releases_late_session(self) -> None:
        import time

        from capability.browserbase_client import create_session

        prev_timeout = os.environ.get("BROWSERBASE_CREATE_TIMEOUT_S")
        prev_attempts = os.environ.get("BROWSERBASE_CREATE_ATTEMPTS")
        os.environ["BROWSERBASE_CREATE_TIMEOUT_S"] = "0.4"
        os.environ["BROWSERBASE_CREATE_ATTEMPTS"] = "2"
        state = {"n": 0, "released": []}

        def _create(**_kwargs):
            state["n"] += 1
            if state["n"] == 1:
                time.sleep(1.2)
                return self._session("orphan")
            return self._session("ok-2")

        def _update(sid, status=None, **_kwargs):
            state["released"].append((str(sid), status))

        client = MagicMock()
        client.sessions.create.side_effect = _create
        client.sessions.update.side_effect = _update
        try:
            with (
                patch("capability.browserbase_client.browserbase_api_key", return_value="k"),
                patch("capability.browserbase_client.browserbase_project_id", return_value="p"),
                patch("capability.browserbase_client.Browserbase", return_value=client),
            ):
                session = create_session(proxies=False, owner="e2e", study_id="s")
                deadline = time.time() + 3
                while time.time() < deadline and not state["released"]:
                    time.sleep(0.05)
        finally:
            if prev_timeout is None:
                os.environ.pop("BROWSERBASE_CREATE_TIMEOUT_S", None)
            else:
                os.environ["BROWSERBASE_CREATE_TIMEOUT_S"] = prev_timeout
            if prev_attempts is None:
                os.environ.pop("BROWSERBASE_CREATE_ATTEMPTS", None)
            else:
                os.environ["BROWSERBASE_CREATE_ATTEMPTS"] = prev_attempts
        self.assertEqual(session.id, "ok-2")
        self.assertTrue(
            any(sid == "orphan" and status == "REQUEST_RELEASE" for sid, status in state["released"]),
            state["released"],
        )


if __name__ == "__main__":
    unittest.main()
