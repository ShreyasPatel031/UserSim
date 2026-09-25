"""Competitor URL liveness and run-issue exclusion."""

from __future__ import annotations

import unittest

from mvp.competitor_urls import (
    annotate_run_issues,
    classify_run_issue,
    filter_live_competitor_urls,
    rewrite_competitor_task,
    same_site,
    scrub_product_summary,
)
from mvp.study import _summary_from_agent_results


async def _fake_fetch(url: str):
    if "height.app" in url:
        raise OSError("SSL_ERROR_SYSCALL in connection to height.app:443")
    if "dead.example" in url:
        return 200, "https://www.atlassian.com/software/jira", "Jira"
    if "shutdown.example" in url:
        return 200, "https://shutdown.example/", "We have shut down. This product is no longer available."
    if "asana.com" in url:
        return 200, "https://asana.com/", "Asana — work management"
    if "shortcut.com" in url:
        return 200, "https://www.shortcut.com/", "Shortcut"
    if "g2.com" in url:
        return 200, "https://www.g2.com/categories/project-management", "Best software"
    return 404, url, "missing"


class CompetitorUrlTests(unittest.IsolatedAsyncioTestCase):
    async def test_drops_tls_dead_and_offsite_redirect(self) -> None:
        live, dropped = await filter_live_competitor_urls(
            [
                "https://height.app/",
                "https://dead.example/",
                "https://asana.com/",
                "https://www.g2.com/categories/project-management",
            ],
            product_url="https://linear.app/",
            fetch=_fake_fetch,
        )
        self.assertEqual(live, ["https://asana.com/"])
        reasons = {url: reason for url, reason in dropped}
        self.assertIn("tls_error", reasons["https://height.app/"])
        self.assertIn("redirected_off_site", reasons["https://dead.example/"])
        self.assertIn("not_a_product_site", reasons["https://www.g2.com/categories/project-management"])

    async def test_shutdown_page_and_www_alias(self) -> None:
        live, dropped = await filter_live_competitor_urls(
            ["https://shutdown.example/", "https://shortcut.com/"],
            product_url="https://linear.app/",
            fetch=_fake_fetch,
        )
        self.assertEqual(live, ["https://www.shortcut.com/"])
        self.assertEqual(dropped[0][1], "defunct_page")

    def test_same_site_subdomain(self) -> None:
        self.assertTrue(same_site("https://asana.com/", "https://app.asana.com/login"))
        self.assertTrue(same_site("https://www.asana.com/", "https://asana.com/"))
        self.assertFalse(same_site("https://height.app/", "https://www.atlassian.com/software/jira"))


class TaskRetargetTests(unittest.TestCase):
    def test_swap_rewrites_prompt_and_title(self) -> None:
        task = {
            "title": "Skim the homepage and note what stands out (vs https://height.app/)",
            "prompt": (
                "Skim the homepage and note what stands out\n\n"
                "You are evaluating the competitor site https://height.app/ only. "
                "Stay on that site — do not open the original product or other rivals."
            ),
            "site_url": "https://height.app/",
            "site_key": "competitor_1",
        }
        rewrite_competitor_task(task, "https://www.atlassian.com/software/jira")
        self.assertEqual(task["site_url"], "https://www.atlassian.com/software/jira")
        self.assertIn("atlassian.com", task["site_label"])
        self.assertIn("(vs https://www.atlassian.com/software/jira)", task["title"])
        self.assertNotIn("height.app", task["title"])
        self.assertNotIn("height.app", task["prompt"])
        self.assertIn("https://www.atlassian.com/software/jira", task["prompt"])


class RunIssueTests(unittest.TestCase):
    def _jira_mismatch(self) -> dict:
        return {
            "agent_id": "t1__p1__competitor_1",
            "persona_name": "Agile Product Manager",
            "task_title": "Skim the homepage and note what stands out (vs https://height.app/)",
            "task_prompt": (
                "Skim the homepage and note what stands out\n\n"
                "You are evaluating the competitor site https://height.app/ only. "
                "Stay on that site — do not open the original product or other rivals."
            ),
            "site_url": "https://www.atlassian.com/software/jira",
            "final_url": "https://www.atlassian.com/software/jira",
            "friction_points": [
                "Users frequently landed on incorrect competitor websites (Jira instead of Height.app)."
            ],
            "what_was_easy": [],
            "quote": "I'm on Jira's website, not Height.app.",
            "product_feedback": "Wrong site.",
            "would_convert": "no",
        }

    def test_prompt_mismatch_is_infrastructure_even_if_final_matches_site_url(self) -> None:
        issue = classify_run_issue(self._jira_mismatch())
        self.assertIsNotNone(issue)
        assert issue is not None
        self.assertEqual(issue["kind"], "infrastructure")
        self.assertIn("height.app", issue["reason"])
        self.assertIn("atlassian.com", issue["reason"])

    def test_off_domain_final_url_is_navigation(self) -> None:
        issue = classify_run_issue(
            {
                "site_url": "https://asana.com/",
                "final_url": "https://www.atlassian.com/software/jira",
                "task_title": "Skim (vs https://asana.com/)",
                "task_prompt": (
                    "Skim\n\nYou are evaluating the competitor site https://asana.com/ only. "
                    "Stay on that site — do not open the original product or other rivals."
                ),
            }
        )
        self.assertIsNotNone(issue)
        assert issue is not None
        self.assertEqual(issue["kind"], "navigation")

    def test_matching_competitor_is_not_a_run_issue(self) -> None:
        self.assertIsNone(
            classify_run_issue(
                {
                    "site_url": "https://asana.com/",
                    "final_url": "https://app.asana.com/0/home",
                    "task_title": "Skim (vs https://asana.com/)",
                    "task_prompt": (
                        "Skim\n\nYou are evaluating the competitor site https://asana.com/ only. "
                        "Stay on that site — do not open the original product or other rivals."
                    ),
                }
            )
        )

    def test_summary_excludes_harness_friction(self) -> None:
        bad = self._jira_mismatch()
        good = {
            "agent_id": "t1__p1__product",
            "persona_name": "Agile Product Manager",
            "task_title": "Skim the homepage",
            "task_prompt": "Skim the homepage",
            "site_url": "https://linear.app/",
            "final_url": "https://linear.app/",
            "friction_points": ["Pricing is hard to find."],
            "what_was_easy": ["The homepage loads quickly."],
            "quote": "Clean homepage.",
            "product_feedback": "Looks professional.",
            "would_convert": "maybe",
        }
        summary = _summary_from_agent_results([bad, good])
        self.assertEqual(summary["top_friction"], ["Pricing is hard to find."])
        self.assertTrue(summary["run_issues"])
        self.assertTrue(bad.get("exclude_from_insights"))
        blob = " ".join(summary["top_friction"]) + " " + " ".join(summary["run_issues"])
        self.assertNotIn("Pricing is hard to find.", " ".join(summary["run_issues"]))
        self.assertIn("height.app", blob)
        self.assertNotIn("incorrect competitor", " ".join(summary["top_friction"]).lower())

    def test_scrub_linear_report_language(self) -> None:
        cleaned = scrub_product_summary(
            {
                "headline": (
                    "Linear's homepage consistently delivers a clean, professional first impression, "
                    "but users struggle with task misdirection to competitor sites when comparative tasks are introduced."
                ),
                "top_friction": [
                    "Users frequently landed on incorrect competitor websites (Jira instead of Height.app), completely derailing comparative tasks.",
                    "Lack of immediate clarity on AI/ML integration capabilities.",
                ],
                "top_strengths": ["Clean, modern, and professional design of the Linear homepage."],
                "conversion_outlook": (
                    "The high rate of misdirection to competitor sites during comparative tasks significantly skews conversion."
                ),
                "recommendations": [
                    {
                        "priority": "high",
                        "action": "Ensure task instructions prevent users from landing on incorrect competitor sites.",
                        "rationale": "Tasks were invalidated because users landed on Jira instead of Height.app.",
                    },
                    {
                        "priority": "medium",
                        "action": "Show AI workflow integration on the homepage.",
                        "rationale": "Engineers could not see how agents fit.",
                    },
                ],
                "segment_fit_rationale": "It fits product teams.",
            }
        )
        self.assertNotIn("misdirection", cleaned["headline"].lower())
        self.assertEqual(
            cleaned["top_friction"],
            ["Lack of immediate clarity on AI/ML integration capabilities."],
        )
        self.assertEqual(len(cleaned["recommendations"]), 1)
        self.assertNotIn("misdirection", cleaned["conversion_outlook"].lower())
        self.assertIn("professional", cleaned["headline"].lower())

    def test_annotate_marks_only_bad_runs(self) -> None:
        bad = self._jira_mismatch()
        good = {
            "site_url": "https://linear.app/",
            "final_url": "https://linear.app/changelog",
            "task_title": "Skim",
            "task_prompt": "Skim",
        }
        issues = annotate_run_issues([bad, good])
        self.assertEqual(len(issues), 1)
        self.assertTrue(bad["exclude_from_insights"])
        self.assertNotIn("exclude_from_insights", good)


if __name__ == "__main__":
    unittest.main()
