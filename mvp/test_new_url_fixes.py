"""Generic fixes from the figma.com home-page run (study 4d947b3f)."""

from __future__ import annotations

import unittest

from mvp.a11y_agent import auth_modal_opened, auth_page, goal_visible, looping, task_kind


def _nodes(n: int, inert: int) -> list[dict]:
    return [{"i": i, "role": "a", "name": f"n{i}", "inert": i < inert} for i in range(n)]


class TaskKindIgnoresRivalAddressTests(unittest.TestCase):
    def test_sketch_domain_does_not_make_a_pricing_task_a_drawing(self):
        task = "Look for pricing or how to get started (vs https://www.sketch.com/)"
        self.assertEqual(task_kind(task), "pricing")
        self.assertTrue(goal_visible(task, {"url": "https://www.sketch.com/pricing/", "title": "Pricing"}))

    def test_real_drawing_tasks_still_draw(self):
        self.assertEqual(task_kind("Sketch a box on the canvas"), "draw")
        self.assertEqual(task_kind("Draw a rectangle (vs https://excalidraw.com/)"), "draw")


class AuthModalTests(unittest.TestCase):
    def test_signup_link_that_opens_a_dialog_on_the_same_page_is_an_account_wall(self):
        before = {"url": "https://www.figma.com/", "nodes": _nodes(20, 0), "dialog": False}
        after = {"url": "https://www.figma.com/", "nodes": _nodes(20, 19), "dialog": False}
        self.assertTrue(auth_modal_opened("https://www.figma.com/signup", before, after))
        after["auth_modal"] = "https://www.figma.com/signup"
        self.assertTrue(auth_page(after))

    def test_ordinary_link_or_navigation_is_not_an_auth_modal(self):
        before = {"url": "https://www.figma.com/", "nodes": _nodes(20, 0)}
        blocked = {"url": "https://www.figma.com/", "nodes": _nodes(20, 19)}
        self.assertFalse(auth_modal_opened("https://www.figma.com/pricing/", before, blocked))
        moved = {"url": "https://www.figma.com/signup", "nodes": _nodes(20, 0)}
        self.assertFalse(auth_modal_opened("https://www.figma.com/signup", before, moved))
        self.assertFalse(auth_modal_opened("https://www.figma.com/signup", before, dict(before)))


class ThreePageLoopTests(unittest.TestCase):
    def test_pricing_trial_home_cycle_is_a_loop(self):
        cycle = [
            ("click Pricing", "https://www.sketch.com/pricing/"),
            ("click Or start a free trial", "https://www.sketch.com/downloads/mac/"),
            ("click Go to Homepage", "https://www.sketch.com/"),
        ]
        trace = [{"step": i + 1, "action": cycle[i % 3][0], "url": cycle[i % 3][1]} for i in range(12)]
        self.assertTrue(looping(trace))
        self.assertFalse(looping(trace[:11]))

    def test_steady_progress_is_not_a_loop(self):
        trace = [{"step": i + 1, "action": f"click item {i}", "url": f"https://x.com/{i}"} for i in range(12)]
        self.assertFalse(looping(trace))


if __name__ == "__main__":
    unittest.main()


class VerdictWithoutRivalRunsTests(unittest.TestCase):
    def test_prompt_says_there_is_no_competitor_comparison(self):
        import asyncio
        import sys
        import types

        from mvp import report_insights

        seen = {}

        async def fake_chat(messages, **kwargs):
            seen["prompt"] = messages[0]["content"]
            return "Figma is good for finding pricing."

        mod = types.ModuleType("capability.gemini_config")
        mod.gemini_chat = fake_chat
        real = sys.modules.get("capability.gemini_config")
        sys.modules["capability.gemini_config"] = mod
        try:
            insights = {
                "product_name": "Figma",
                "verdict": {"good_for": ["Pricing: 1/1"], "trails": [], "unfinished": []},
                "sites": [{"site_key": "product", "site_label": "Figma", "n": 1, "ok": 1}],
                "run_issues": [{"kind": "session"}] * 11,
            }
            asyncio.run(report_insights.write_verdict_summary({}, insights))
        finally:
            if real is not None:
                sys.modules["capability.gemini_config"] = real
        self.assertIn('"competitors_compared": []', seen["prompt"])
        self.assertIn('"runs_that_never_opened": 11', seen["prompt"])
        self.assertIn("compare with no one", seen["prompt"])


class StepNoiseTests(unittest.TestCase):
    def _insights(self, mine_steps, rival_steps, mine_t=9.0, rival_t=6.0):
        return {
            "sites": [
                {"site_key": "product", "site_label": "Figma", "n": 2},
                {"site_key": "competitor_1", "site_label": "Sketch", "n": 2},
            ],
            "by_task": [{
                "title": "Look for pricing",
                "sites": {
                    "product": {"n": 2, "ok": 2, "median_steps": mine_steps, "median_time_s": mine_t},
                    "competitor_1": {"n": 2, "ok": 2, "median_steps": rival_steps, "median_time_s": rival_t},
                },
            }],
        }

    def test_one_step_and_three_seconds_is_level(self):
        from mvp.report_insights import verdict

        v = verdict(self._insights(2.0, 1.0), {"url": "https://www.figma.com/"})
        self.assertEqual(v["trails"], [])
        self.assertIn("level with the competitors", v["good_for"][0])

    def test_a_real_gap_still_trails(self):
        from mvp.report_insights import verdict

        v = verdict(self._insights(5.0, 2.0, 40.0, 10.0), {"url": "https://www.figma.com/"})
        self.assertEqual(len(v["trails"]), 1)
        self.assertIn("Sketch (2 steps vs Figma's 5)", v["trails"][0])


class LinkNavigationWaitTests(unittest.TestCase):
    def test_only_real_links_to_another_page_wait(self):
        from mvp.a11y_agent import _link_leaves_page

        self.assertTrue(_link_leaves_page("https://www.figma.com/pricing/", "https://www.figma.com/"))
        self.assertFalse(_link_leaves_page("https://www.figma.com/#top", "https://www.figma.com/"))
        self.assertFalse(_link_leaves_page("javascript:void(0)", "https://www.figma.com/"))
        self.assertFalse(_link_leaves_page("", "https://www.figma.com/"))

    def test_waits_for_the_url_to_change(self):
        import asyncio

        from mvp.a11y_agent import _await_link_navigation

        class Page:
            url = "https://www.figma.com/"
            waited = []

            async def wait_for_url(self, pred, timeout):
                self.waited.append(timeout)
                self.url = "https://www.figma.com/pricing/"
                assert pred(self.url)

            async def wait_for_load_state(self, *a, **k):
                return None

        page = Page()
        asyncio.run(_await_link_navigation(page, "https://www.figma.com/pricing/", "https://www.figma.com/"))
        self.assertEqual(page.waited, [2500])


class UnlabeledClickTests(unittest.TestCase):
    def test_a_click_with_no_name_reads_as_words(self):
        from mvp.a11y_agent import action_label
        from mvp.report_insights import human_action

        self.assertEqual(action_label({"act": "click", "name": ""}), "click an unlabeled control")
        self.assertEqual(human_action("click"), "click an unlabeled control")
        self.assertEqual(human_action("click add-project"), "click add project")


class ReportNoiseTests(unittest.TestCase):
    def test_signup_advice_is_dropped_from_the_verdict(self):
        from mvp.report_insights import drop_harness_sentences

        text = "Figma is good for pricing. The most useful fix is to improve the signup process for Figma."
        self.assertEqual(drop_harness_sentences(text), "Figma is good for pricing.")

    def test_consent_buttons_are_not_no_change_findings(self):
        from mvp.report_insights import _CONSENT_CLICK_RE

        self.assertTrue(_CONSENT_CLICK_RE.match("click Accept"))
        self.assertTrue(_CONSENT_CLICK_RE.match("click Accept all cookies"))
        self.assertFalse(_CONSENT_CLICK_RE.match("click Create project"))


class BrowserOpenRetryTests(unittest.TestCase):
    def test_retries_a_failed_open_while_budget_is_left(self):
        import asyncio
        import time
        from unittest import mock

        from mvp import a11y_agent

        calls = []

        async def once(boot, url):
            calls.append(url)
            if len(calls) < 3:
                raise RuntimeError("TimeoutError()")
            return ("bb", "browser", "page", 1.0, 2.0)

        async def no_sleep(_s):
            return None

        with mock.patch.object(a11y_agent, "_open_agent_session_once", once), \
                mock.patch.object(a11y_agent.asyncio, "sleep", no_sleep):
            got = asyncio.run(a11y_agent._open_agent_session(None, "https://x.com/", time.monotonic() + 400))
        self.assertEqual(got[0], "bb")
        self.assertEqual(len(calls), 3)

    def test_gives_up_when_the_budget_is_short(self):
        import asyncio
        import time
        from unittest import mock

        from mvp import a11y_agent

        calls = []

        async def once(boot, url):
            calls.append(url)
            raise RuntimeError("TimeoutError()")

        with mock.patch.object(a11y_agent, "_open_agent_session_once", once):
            with self.assertRaises(RuntimeError):
                asyncio.run(a11y_agent._open_agent_session(None, "https://x.com/", time.monotonic() + 60))
        self.assertEqual(len(calls), 1)


class PricingPageUnderAnotherNameTests(unittest.TestCase):
    def test_premium_path_or_priced_plans_count_as_pricing(self):
        task = "Look for pricing or how to get started (vs https://doodle.com/)"
        self.assertTrue(goal_visible(task, {"url": "https://doodle.com/en/premium", "title": "Doodle Premium"}))
        text = "Choose your plan Free $0 Pro $6.95 per user / month Team $8.95 per user / month"
        self.assertTrue(goal_visible(task, {"url": "https://x.com/compare", "title": "Compare", "text": text}))

    def test_one_price_on_a_home_page_is_not_the_pricing_page(self):
        task = "Look for pricing or how to get started"
        self.assertFalse(goal_visible(task, {"url": "https://x.com/", "title": "X", "text": "Start free, then $10/month"}))


class SignupTimeoutWordingTests(unittest.TestCase):
    def test_account_wall_advice_is_dropped(self):
        from mvp.report_insights import drop_harness_sentences

        text = ("Airtable is good for pricing. The most useful fix is to address the account creation "
                "wall encountered when trying to create a new base.")
        self.assertEqual(drop_harness_sentences(text), "Airtable is good for pricing.")
        self.assertEqual(drop_harness_sentences("Pricing takes one click."), "Pricing takes one click.")

    def test_a_signup_that_timed_out_is_a_limit_of_the_test(self):
        from mvp.report_insights import build_report_insights

        run = {
            "agent_id": "t1__p1__product", "site_key": "product", "task_title": "Create a new base",
            "site_url": "https://airtable.com/", "completed": False, "stop_reason": "needs_account",
            "final_url": "https://airtable.com/signup", "page_open_at_ts": 1.0,
            "final_screenshot_url": "/api/studies/s1/agents/t1__p1__product/screenshots/final.png", "first_action_at_ts": 2.0,
            "failed_step": {"phase": "needs_account", "reason": "signup did not finish (timeout)", "step": 2},
            "trace": [
                {"step": 0, "action": "Opened https://airtable.com/", "url": "https://airtable.com/"},
                {"step": 1, "action": "click Sign up for free", "url": "https://airtable.com/signup", "changed": True},
                {"step": 2, "action": "signup did not finish (timeout)", "url": "https://airtable.com/signup"},
            ],
        }
        insights = build_report_insights({"id": "s1", "url": "https://airtable.com/", "agent_results": [run], "activity_log": []})
        claims = " ".join(str(c.get("claim")) for c in insights.get("weaknesses") or [])
        self.assertIn("limit of the test", claims)
