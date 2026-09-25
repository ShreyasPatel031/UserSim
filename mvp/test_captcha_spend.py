"""Spend caps refuse CapSolver before any HTTP. No live solves."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class SpendGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.tmp.name) / "ledger.jsonl"
        self.env = patch.dict(
            os.environ,
            {
                "CAPTCHA_SPEND_LEDGER": str(self.ledger),
                "CAPSOLVER_API_KEY": "unit-test-key",
                "MVP_CAPTCHA_PAID_HOSTS": "trello.com",
                "MVP_CAPTCHA_API": "capsolver",
            },
            clear=False,
        )
        self.env.start()
        # Context vars leak across tests if a previous test bound a site.
        from mvp.captcha_spend import bind_signup

        bind_signup("", 0)

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def _rows(self) -> list[dict]:
        if not self.ledger.is_file():
            return []
        return [json.loads(line) for line in self.ledger.read_text().splitlines() if line.strip()]

    def test_host_not_allowlisted_makes_no_http(self) -> None:
        from mvp.captcha import _capsolver_solve
        from mvp.captcha_spend import bind_signup

        bind_signup("github.com", 1)
        with patch("mvp.captcha.httpx.post", side_effect=AssertionError("http")):
            token = _capsolver_solve(
                "should-not-be-used",
                sitekey="6Le",
                page_url="https://github.com/signup",
                captcha_type="recaptcha_enterprise",
                action=None,
                timeout_s=5,
                blocking=True,
            )
        self.assertIsNone(token)
        self.assertEqual(self._rows()[-1]["reason"], "host_not_paid")
        self.assertNotIn("unit-test-key", self.ledger.read_text())

    def test_arkose_and_hcaptcha_are_refused_with_no_http(self) -> None:
        from mvp.captcha import _capsolver_solve
        from mvp.captcha_spend import begin_signup_attempt

        os.environ["MVP_CAPTCHA_PAID_HOSTS"] = "github.com,supabase.com"
        begin_signup_attempt("github.com")
        with patch("mvp.captcha.httpx.post", side_effect=AssertionError("http")):
            arkose = _capsolver_solve(
                "",
                sitekey="ARK",
                page_url="https://github.com/signup",
                captcha_type="arkose",
                action=None,
                timeout_s=5,
                blocking=True,
            )
        self.assertIsNone(arkose)
        self.assertEqual(self._rows()[-1]["reason"], "unsupported_or_unpriced")

        begin_signup_attempt("supabase.com")
        with patch("mvp.captcha.httpx.post", side_effect=AssertionError("http")):
            hcap = _capsolver_solve(
                "",
                sitekey="4ca",
                page_url="https://supabase.com",
                captcha_type="hcaptcha",
                action=None,
                timeout_s=5,
                blocking=True,
            )
        self.assertIsNone(hcap)
        self.assertEqual(self._rows()[-1]["reason"], "unsupported_or_unpriced")
        self.assertNotIn("clientKey", self.ledger.read_text())

    def test_not_blocking_makes_no_http(self) -> None:
        from mvp.captcha import _capsolver_solve
        from mvp.captcha_spend import begin_signup_attempt

        begin_signup_attempt("trello.com")
        with patch("mvp.captcha.httpx.post", side_effect=AssertionError("http")):
            token = _capsolver_solve(
                "",
                sitekey="6Le",
                page_url="https://trello.com/signup",
                captcha_type="recaptcha_enterprise",
                action=None,
                timeout_s=5,
                blocking=False,
            )
        self.assertIsNone(token)
        self.assertEqual(self._rows()[-1]["reason"], "not_blocking")

    def test_allowed_solve_logs_task_without_the_key(self) -> None:
        from mvp.captcha import _capsolver_solve
        from mvp.captcha_spend import begin_signup_attempt

        begin_signup_attempt("trello.com")

        def fake_post(url, json=None, timeout=None):  # noqa: A002
            class Resp:
                def json(self):
                    if url.endswith("/getBalance"):
                        return {"errorId": 0, "balance": 19.5}
                    if url.endswith("/createTask"):
                        self.sent = json
                        return {"errorId": 0, "taskId": "task-abc"}
                    if url.endswith("/getTaskResult"):
                        return {
                            "errorId": 0,
                            "status": "ready",
                            "solution": {"gRecaptchaResponse": "token-value"},
                        }
                    raise AssertionError(url)

            return Resp()

        with patch("mvp.captcha.httpx.post", side_effect=fake_post):
            token = _capsolver_solve(
                "vault-key-must-not-send",
                sitekey="6Le9VxMn",
                page_url="https://id.atlassian.com/signup",
                captcha_type="recaptcha_enterprise",
                action=None,
                timeout_s=5,
                blocking=True,
            )
        self.assertEqual(token, "token-value")
        tasks = [r for r in self._rows() if r.get("event") == "createTask"]
        self.assertEqual(len(tasks), 1)
        row = tasks[0]
        self.assertEqual(row["site"], "trello.com")
        self.assertEqual(row["captcha_type"], "recaptcha_enterprise")
        self.assertEqual(row["task_id"], "task-abc")
        self.assertTrue(row["solved"])
        self.assertGreater(row["cost"], 0)
        text = self.ledger.read_text()
        self.assertNotIn("unit-test-key", text)
        self.assertNotIn("vault-key-must-not-send", text)
        self.assertNotIn("clientKey", text)

    def test_fourth_solve_and_third_signup_are_refused(self) -> None:
        from mvp.captcha import _capsolver_solve
        from mvp.captcha_spend import SpendCapError, begin_signup_attempt, record_task

        attempt = begin_signup_attempt("trello.com")
        for i in range(3):
            record_task(
                site="trello.com",
                captcha_type="recaptcha_enterprise",
                task_type="ReCaptchaV2EnterpriseTaskProxyLess",
                task_id=f"seed-{i}",
                solved=False,
                cost=0.001,
                balance_before=20.0,
                balance_after=19.999,
            )
        with patch("mvp.captcha.httpx.post", side_effect=AssertionError("http")):
            token = _capsolver_solve(
                "",
                sitekey="6Le",
                page_url="https://trello.com/signup",
                captcha_type="recaptcha_enterprise",
                action=None,
                timeout_s=5,
                blocking=True,
            )
        self.assertIsNone(token)
        self.assertEqual(self._rows()[-1]["reason"], "solve_attempt_cap")
        self.assertEqual(attempt, 1)
        begin_signup_attempt("trello.com")
        with self.assertRaises(SpendCapError):
            begin_signup_attempt("trello.com")

    def test_total_cap_refuses_before_http(self) -> None:
        from mvp.captcha import _capsolver_solve
        from mvp.captcha_spend import begin_signup_attempt, record_task

        begin_signup_attempt("trello.com")
        record_task(
            site="other.example",
            captcha_type="recaptcha_enterprise",
            task_type="ReCaptchaV2EnterpriseTaskProxyLess",
            task_id="seed-cap",
            solved=True,
            cost=15.0,
            balance_before=20.0,
            balance_after=5.0,
        )
        with patch("mvp.captcha.httpx.post", side_effect=AssertionError("http")):
            token = _capsolver_solve(
                "",
                sitekey="6Le",
                page_url="https://trello.com/signup",
                captcha_type="recaptcha_enterprise",
                action=None,
                timeout_s=5,
                blocking=True,
            )
        self.assertIsNone(token)
        self.assertEqual(self._rows()[-1]["reason"], "total_cap")


if __name__ == "__main__":
    unittest.main()
