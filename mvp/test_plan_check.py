"""Planner-only dry run: validation rules and the no-browser dry_run_plan path (Gemini mocked)."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest import mock

from mvp import plan_check

LINEAR = "https://linear.app/"
JIRA = "https://www.atlassian.com/software/jira/"
ASANA = "https://asana.com/"


def _plan(**over):
    plan = {
        "mode": "compare",
        "product": "Linear",
        "segment": "Engineering teams",
        "competitors": [JIRA, ASANA],
        "competitor_names": {JIRA: "Jira", ASANA: "Asana"},
        "personas": [{"name": n, "favors": "product"} for n in ("Priya Okafor", "Kenji Sato", "Mei Iyer")],
        "task_specs": [
            {"prompt": "Create an issue", "favors": "product"},
            {"prompt": "Plan a cycle", "favors": "product"},
            {"prompt": "Build a board", "favors": JIRA},
            {"prompt": "Write a sprint report", "favors": JIRA},
            {"prompt": "Make a timeline", "favors": ASANA},
            {"prompt": "Assign a task", "favors": ASANA},
        ],
    }
    plan["tasks"] = [t["prompt"] for t in plan["task_specs"]]
    plan.update(over)
    return plan


def _live(*urls, dead=()):
    return [{"url": u, "live": True, "reason": "ok"} for u in urls] + [
        {"url": u, "live": False, "reason": "http_404"} for u in dead
    ]


def _by_name(checks):
    return {c["name"]: c for c in checks}


class ValidatePlanTests(unittest.TestCase):
    def test_a_good_plan_passes_every_check(self):
        checks = plan_check.validate_plan(_plan(), product_url=LINEAR, rivals=_live(JIRA, ASANA), elapsed_s=9.0)
        self.assertEqual([c["name"] for c in checks if not c["ok"]], [])
        self.assertEqual(
            set(_by_name(checks)),
            {"plan", "live_rivals", "no_chatbot_rival", "unique_personas", "tasks_per_site", "plan_time"},
        )

    def test_no_plan_fails(self):
        got = _by_name(plan_check.validate_plan(None, product_url=LINEAR, rivals=[], elapsed_s=1.0))
        self.assertFalse(got["plan"]["ok"])
        self.assertFalse(got["live_rivals"]["ok"])
        self.assertFalse(got["tasks_per_site"]["ok"])

    def test_classic_fallback_counts_as_rejected(self):
        plan = {"product": "Linear", "competitors": [JIRA, ASANA], "tasks": ["a", "b"]}
        got = _by_name(plan_check.validate_plan(plan, product_url=LINEAR, rivals=_live(JIRA, ASANA), elapsed_s=1.0))
        self.assertFalse(got["plan"]["ok"])

    def test_a_rival_the_verify_step_rejected_but_kept_fails(self):
        plan = _plan(verified={"rejected": ["https://asana.com"], "redo": False})
        got = _by_name(plan_check.validate_plan(plan, product_url=LINEAR, rivals=_live(JIRA, ASANA), elapsed_s=1.0))
        self.assertFalse(got["plan"]["ok"])
        self.assertIn("asana.com", got["plan"]["detail"])

    def test_fewer_than_two_live_rivals_fails(self):
        got = _by_name(plan_check.validate_plan(_plan(), product_url=LINEAR, rivals=_live(JIRA, dead=[ASANA]), elapsed_s=1.0))
        self.assertFalse(got["live_rivals"]["ok"])
        self.assertIn("http_404", got["live_rivals"]["detail"])

    def test_a_chatbot_rival_fails_unless_the_product_is_one(self):
        bot = "https://chatgpt.com/"
        plan = _plan(competitors=[JIRA, bot])
        got = _by_name(plan_check.validate_plan(plan, product_url=LINEAR, rivals=_live(JIRA, bot), elapsed_s=1.0))
        self.assertFalse(got["no_chatbot_rival"]["ok"])
        got = _by_name(plan_check.validate_plan(plan, product_url="https://claude.ai/", rivals=_live(JIRA, bot), elapsed_s=1.0))
        self.assertTrue(got["no_chatbot_rival"]["ok"])

    def test_a_chatbot_vendors_product_page_is_not_a_chatbot(self):
        api = "https://www.anthropic.com/api/"
        got = _by_name(plan_check.validate_plan(_plan(competitors=[JIRA, api]), product_url="https://openrouter.ai/",
                                                rivals=_live(JIRA, api), elapsed_s=1.0))
        self.assertTrue(got["no_chatbot_rival"]["ok"])

    def test_repeated_persona_names_fail(self):
        plan = _plan(personas=[{"name": "Alex Chen"}, {"name": "alex chen"}, {"name": "Mei Iyer"}])
        got = _by_name(plan_check.validate_plan(plan, product_url=LINEAR, rivals=_live(JIRA, ASANA), elapsed_s=1.0))
        self.assertFalse(got["unique_personas"]["ok"])

    def test_a_site_with_one_task_fails(self):
        specs = _plan()["task_specs"][:-1]
        got = _by_name(plan_check.validate_plan(_plan(task_specs=specs), product_url=LINEAR,
                                                rivals=_live(JIRA, ASANA), elapsed_s=1.0))
        self.assertFalse(got["tasks_per_site"]["ok"])
        self.assertIn("Asana", got["tasks_per_site"]["detail"])

    def test_a_slow_plan_fails(self):
        got = _by_name(plan_check.validate_plan(_plan(), product_url=LINEAR, rivals=_live(JIRA, ASANA), elapsed_s=25.0))
        self.assertFalse(got["plan_time"]["ok"])


class DryRunPlanTests(unittest.TestCase):
    def _run(self, plan, starter=None):
        from capability import gemini_config as gc

        async def fake_plan(url, **kw):
            gc._note_usage("gemini-2.5-flash", {"usageMetadata": {"promptTokenCount": 3000, "candidatesTokenCount": 800}}, 5.0)  # pragma: allowlist secret
            return plan

        async def fake_starter(url, **kw):
            gc._note_usage("gemini-2.5-flash", {"usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 100}}, 2.0)  # pragma: allowlist secret
            return starter

        async def fetch(url):
            return 200, url, "<html>ok</html>"

        with mock.patch.dict(os.environ, {"MVP_STUDY_MODE": "compare", "MVP_EARLY_START": "1", "MVP_LLM_LOG_TOKENS": "0"}), \
                mock.patch("mvp.fast_plan.plan_from_url", fake_plan), \
                mock.patch("mvp.early_start.starter_plan", fake_starter), \
                mock.patch("mvp.early_start.start_early_agent") as early_agent, \
                mock.patch("mvp.study.create_study") as create:
            out = asyncio.run(plan_check.dry_run_plan(LINEAR, fetch=fetch))
        early_agent.assert_not_called()
        create.assert_not_called()
        return out

    def test_returns_the_spliced_plan_checks_and_token_cost(self):
        starter = {"product": "Linear", "persona": {"name": "Hana Novak", "favors": "product"}, "task": "Create an issue"}
        out = self._run(_plan(), starter)
        self.assertTrue(out["dry_run"])
        self.assertTrue(out["ok"], out["validation"])
        self.assertEqual(out["personas"][0]["name"], "Hana Novak")
        self.assertEqual([r["url"] for r in out["rivals"]], [JIRA, ASANA])
        self.assertEqual(out["rivals"][0]["name"], "Jira")
        self.assertEqual(len(out["tasks"]), 6)
        usage = out["usage"]
        self.assertEqual((usage["gemini_calls"], usage["input_tokens"], usage["output_tokens"]), (2, 4000, 900))
        # 4000 * $0.30/M + 900 * $2.50/M
        self.assertAlmostEqual(usage["est_cost_usd"], 0.00345, places=6)

    def test_no_plan_is_reported_not_raised(self):
        out = self._run(None)
        self.assertFalse(out["ok"])
        self.assertEqual(out["personas"], [])
        self.assertFalse(_by_name(out["validation"])["plan"]["ok"])


if __name__ == "__main__":
    unittest.main()
