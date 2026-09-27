"""Timeouts and compare-shape fixes from study 7b5f0af9 (Zo vs Zapier, n8n, ChatGPT)."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest import mock


class AgentDeadline(unittest.TestCase):
    def test_own_480s_from_page_open(self) -> None:
        from mvp.a11y_agent import agent_deadline

        with mock.patch.dict(os.environ, {"MVP_AGENT_BUDGET_S": "", "MVP_AGENT_FINISH_MARGIN_S": ""}):
            self.assertEqual(agent_deadline(1000.0, None), 1000.0 + 480 - 30)
            # The study clock stays a ceiling, never extends an agent.
            self.assertEqual(agent_deadline(1000.0, 1200.0), 1200.0)
            self.assertEqual(agent_deadline(1000.0, 9999.0), 1450.0)


class TimeoutRelabel(unittest.TestCase):
    def _run(self, **kw):
        base = {
            "agent_id": "t2__p2__competitor_2",
            "site_url": "https://www.n8n.io/",
            "final_url": "https://n8n.io/ai/",
            "stop_reason": "done",
            "signup": {"ok": False, "reason": "TimeoutError()", "seconds": 61.4},
            "website_eval": {"verdict": "partial"},
            "friction_points": ["The signup process timed out, preventing the user from proceeding."],
            "trace": [
                {"step": 3, "action": "click Get Started"},
                {"step": 4, "action": "signup did not finish (TimeoutError())"},
                {"step": 5, "action": "click Explore AI"},
            ],
        }
        base.update(kw)
        return base

    def test_signup_only_timeout_is_not_a_run_timeout(self) -> None:
        from mvp.report_insights import _usersim_failure

        self.assertIsNone(_usersim_failure(self._run(), "https://www.zo.computer/"))

    def test_real_run_timeout_still_flagged(self) -> None:
        from mvp.report_insights import _usersim_failure

        run = self._run(
            browser_error="agent wall: deadline exceeded", website_eval=None, stop_reason="timeout",
            failed_step={"phase": "timeout", "reason": "agent wall"},
        )
        self.assertEqual((_usersim_failure(run, "https://www.zo.computer/") or {}).get("kind"), "timeout")

    def test_signup_captcha_then_website_verdict_not_flagged(self) -> None:
        from mvp.report_insights import _usersim_failure

        run = self._run(
            signup={"ok": False, "reason": "captcha_unsolved (no_time_left)"},
            friction_points=[],
            trace=[{"step": 2, "action": "blocked at signup: captcha unsolved (no_time_left)"}],
        )
        self.assertIsNone(_usersim_failure(run, "https://www.zo.computer/"))


class SignupShare(unittest.TestCase):
    def setUp(self) -> None:
        from mvp import signup_share

        signup_share._SHARED.clear()

    def test_retryable(self) -> None:
        from mvp.signup_share import retryable

        for r in ("email_timeout", "TimeoutError()", "timeout"):
            self.assertTrue(retryable(r), r)
        for r in ("account_exists", "captcha_unsolved (paid_refused)", "email_rejected: x"):
            self.assertFalse(retryable(r), r)

    def test_remember_is_per_study_and_site(self) -> None:
        from mvp import signup_share

        signup_share.remember("s1", "zo.computer", [{"name": "a", "value": "b", "domain": ".zo.computer", "path": "/"}], "https://x.zo.computer/")
        self.assertTrue(signup_share.has("s1", "zo.computer"))
        self.assertFalse(signup_share.has("s2", "zo.computer"))
        self.assertFalse(signup_share.has("s1", "zapier.com"))
        with mock.patch.dict(os.environ, {"MVP_SIGNUP_SHARE": "0"}):
            self.assertFalse(signup_share.has("s1", "zo.computer"))

    def test_email_wait_stops_early_once_a_study_session_exists(self) -> None:
        from mvp import signup_share
        from mvp.signup_in_session import _wait_mail_or_share

        calls: list[float] = []

        class Inbox:
            def wait(self, host, since, timeout_s, seen):
                calls.append(timeout_s)
                return None

        signup_share.remember("s1", "zo.computer", [{"name": "a", "value": "b", "domain": ".zo.computer", "path": "/"}], "u")
        clock = {"t": 0.0}

        def fake_time() -> float:
            return clock["t"]

        def wait_adv(host, since, timeout_s, seen):
            calls.append(timeout_s)
            clock["t"] += timeout_s
            return None

        inbox = Inbox()
        inbox.wait = wait_adv  # type: ignore[method-assign]
        with mock.patch("mvp.signup_in_session.time.time", fake_time), mock.patch.dict(os.environ, {"MVP_SIGNUP_SHARED_EMAIL_WAIT_S": "40"}):
            out = asyncio.run(_wait_mail_or_share(inbox, "zo.computer", 0.0, 75.0, set(), "s1"))
        self.assertIsNone(out)
        self.assertEqual(sum(calls), 45.0)  # 15 + 15 + 15, not 75
        calls.clear()
        clock["t"] = 0.0
        with mock.patch("mvp.signup_in_session.time.time", fake_time):
            asyncio.run(_wait_mail_or_share(inbox, "zo.computer", 0.0, 75.0, set(), "other-study"))
        self.assertEqual(sum(calls), 75.0)


class CaptchaStudyHosts(unittest.TestCase):
    def test_study_host_becomes_payable(self) -> None:
        from mvp import captcha_spend as cs

        cs._STUDY_HOSTS.clear()
        with mock.patch.dict(os.environ, {"MVP_CAPTCHA_PAID_HOSTS": "", "MVP_CAPTCHA_PAY_STUDY_SITES": ""}):
            self.assertNotIn("zapier.com", cs.paid_hosts())
            cs.allow_study_host("www.zapier.com")
            self.assertIn("zapier.com", cs.paid_hosts())
        with mock.patch.dict(os.environ, {"MVP_CAPTCHA_PAY_STUDY_SITES": "0", "MVP_CAPTCHA_PAID_HOSTS": ""}):
            self.assertNotIn("zapier.com", cs.paid_hosts())
        cs._STUDY_HOSTS.clear()

    def test_competitor_signup_cap_fits_a_captcha(self) -> None:
        from mvp.a11y_agent import competitor_signup_timeout_s

        with mock.patch.dict(os.environ, {"MVP_SIGNUP_COMPETITOR_TIMEOUT_S": ""}):
            self.assertGreaterEqual(competitor_signup_timeout_s(), 60.0)


class CompareShape(unittest.TestCase):
    personas = [
        {"id": "p1", "favors": "product"},
        {"id": "p2", "favors": "product"},
        {"id": "p3", "favors": "https://zapier.com/"},
        {"id": "p4", "favors": "https://n8n.io/"},
        {"id": "p5", "favors": "product"},
        {"id": "p6", "favors": ""},
    ]
    tasks = [
        {"id": "t1", "favors": "product"},
        {"id": "t2", "favors": "https://www.n8n.io/"},
        {"id": "t3", "favors": "product"},
        {"id": "t4", "favors": "https://zapier.com"},
        {"id": "t5", "favors": ""},
        {"id": "t6", "favors": "product"},
    ]
    comps = ["https://zapier.com/", "https://n8n.io/"]

    def test_competitor_cells_two_by_two(self) -> None:
        from mvp.fast_plan import competitor_cells

        cells = competitor_cells(self.personas, self.tasks, self.comps, n_personas=2, n_tasks=2)
        self.assertEqual(cells["https://zapier.com/"], {"personas": [0, 2], "tasks": [0, 3]})
        self.assertEqual(cells["https://n8n.io/"], {"personas": [0, 3], "tasks": [0, 1]})

    def test_sparse_matrix_is_44_agents(self) -> None:
        from mvp.fast_plan import competitor_cells
        from mvp.study import expand_full_matrix

        cells = competitor_cells(self.personas, self.tasks, self.comps, n_personas=2, n_tasks=2)
        rows = expand_full_matrix(
            [dict(t, title=t["id"], prompt=t["id"]) for t in self.tasks],
            self.personas,
            product_url="https://www.zo.computer/",
            competitors=self.comps,
            competitor_cells=[cells[c] for c in self.comps],
        )
        by_site: dict[str, int] = {}
        for r in rows:
            by_site[r["site_key"]] = by_site.get(r["site_key"], 0) + 1
        self.assertEqual(by_site, {"product": 36, "competitor_1": 4, "competitor_2": 4})
        # Six personas survive (the old default trimmed to 4 and ran p5 as p1).
        self.assertEqual({r["persona_id"] for r in rows if r["site_key"] == "product"}, {f"p{i}" for i in range(1, 7)})

    def test_assistants_are_not_rivals(self) -> None:
        from mvp.fast_plan import is_general_assistant, pick_competitors

        self.assertTrue(is_general_assistant("https://chatgpt.com/"))
        self.assertTrue(is_general_assistant("ChatGPT"))
        self.assertFalse(is_general_assistant("https://zapier.com/"))
        picked = pick_competitors(["https://zapier.com/", "https://chatgpt.com/", "https://n8n.io/"], "zo.computer", limit=2)
        self.assertEqual(len(picked), 2)
        self.assertFalse(any("chatgpt" in p for p in picked))


if __name__ == "__main__":
    unittest.main()
