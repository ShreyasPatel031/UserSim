"""Competitor URL liveness and run-issue exclusion."""

from __future__ import annotations

import unittest

from mvp.competitor_urls import (
    annotate_run_issues,
    classify_run_issue,
    filter_live_competitor_urls,
    insight_view,
    looks_like_product_page,
    rewrite_competitor_task,
    same_site,
    scrub_product_summary,
    unwrap_search_url,
)
from mvp.study import _summary_from_agent_results


_PRODUCT_PAGE_BODY = (
    "<html><head><title>{title}</title></head><body>"
    "<h1>{title}</h1><p>Welcome to {title}. We help teams manage work efficiently. "
    "Join thousands of companies that trust us to deliver great results. "
    "Get started today and see why customers love our product.</p>"
    "<a href='/pricing'>Pricing</a> <a href='/signup'>Sign up</a></body></html>"
)


async def _fake_fetch(url: str):
    if "height.app" in url:
        raise OSError("SSL_ERROR_SYSCALL in connection to height.app:443")
    if "dead.example" in url:
        return 200, "https://www.atlassian.com/software/jira", "Jira"
    if "shutdown.example" in url:
        return 200, "https://shutdown.example/", "We have shut down. This product is no longer available."
    if "asana.com" in url:
        return 200, "https://asana.com/", _PRODUCT_PAGE_BODY.format(title="Asana — work management")
    if "shortcut.com" in url:
        return 200, "https://www.shortcut.com/", _PRODUCT_PAGE_BODY.format(title="Shortcut")
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

    def test_same_site_product_app_domain(self) -> None:
        # Every successful n8n signup lands on <workspace>.app.n8n.cloud.
        self.assertTrue(same_site("https://riveralabs0456.app.n8n.cloud/", "https://n8n.io/"))
        self.assertTrue(same_site("https://n8n.io/", "https://app.n8n.cloud/signin"))
        self.assertFalse(same_site("https://n8n.cloud.evil.com/", "https://n8n.io/"))

    def test_unwraps_duckduckgo_redirects(self) -> None:
        raw = (
            "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.tldraw.com%2F"
            "&rut=abc"
        )
        self.assertEqual(unwrap_search_url(raw), "https://www.tldraw.com/")
        self.assertTrue(looks_like_product_page("https://www.figma.com/figjam/"))
        self.assertTrue(looks_like_product_page("https://miro.com/"))
        self.assertFalse(
            looks_like_product_page("https://affine.pro/blog/excalidraw-alternative")
        )
        self.assertFalse(looks_like_product_page("https://www.g2.com/products/linear"))


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

    def test_browser_partial_is_infrastructure_even_on_the_right_domain(self) -> None:
        issue = classify_run_issue(
            {
                "site_url": "https://linear.app/",
                "final_url": "https://linear.app/",
                "task_title": "Skim",
                "task_prompt": "Skim",
                "mode": "browser_partial",
                "browser_error": "Browserbase create concurrency cap busy",
                "friction_points": ["Browser session ended before the task finished"],
            }
        )
        self.assertIsNotNone(issue)
        assert issue is not None
        self.assertEqual(issue["kind"], "infrastructure")
        summary = _summary_from_agent_results(
            [
                {
                    "agent_id": "partial",
                    "persona_name": "PM",
                    "site_url": "https://linear.app/",
                    "final_url": "https://linear.app/",
                    "task_title": "Skim",
                    "task_prompt": "Skim",
                    "mode": "browser_partial",
                    "browser_error": "429",
                    "friction_points": ["Browser session ended before the task finished"],
                    "what_was_easy": [],
                    "quote": "The browser died.",
                    "would_convert": "no",
                },
                {
                    "agent_id": "ok",
                    "persona_name": "PM",
                    "site_url": "https://linear.app/",
                    "final_url": "https://linear.app/",
                    "task_title": "Skim",
                    "task_prompt": "Skim",
                    "friction_points": ["Pricing is hard to find."],
                    "what_was_easy": [],
                    "quote": "Clean page.",
                    "would_convert": "maybe",
                },
            ]
        )
        self.assertEqual(summary["top_friction"], ["Pricing is hard to find."])
        self.assertTrue(summary["run_issues"])
        self.assertNotIn("browser session ended", " ".join(summary["top_friction"]).lower())

    def test_on_target_competitor_is_not_called_a_wrong_site(self) -> None:
        cleaned = insight_view(
            {
                "friction_points": [
                    "The user was on the wrong website (Jira instead of Linear) for the given task.",
                    "Pricing is hard to find.",
                ],
                "quote": "I'm on the wrong website, Jira instead of Linear.",
                "product_feedback": "Landing on Jira is completely off-topic.",
            }
        )
        self.assertEqual(cleaned["friction_points"], ["Pricing is hard to find."])
        self.assertEqual(cleaned["quote"], "")

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
        self.assertEqual(bad["run_issue"]["persona_name"], "Agile Product Manager")
        self.assertNotIn("exclude_from_insights", good)


class IdentityVerificationTests(unittest.IsolatedAsyncioTestCase):
    """Verify page content matches the expected product name."""

    async def test_different_company_with_generic_domain_rejected(self):
        """A page at a generic domain that doesn't mention the expected product is wrong_company."""
        from mvp.competitor_urls import probe_competitor_url

        async def fetch_different_company(url):
            return (
                200,
                url,
                "<html><head><title>ACME Software Solutions</title>"
                '<meta name="description" content="ACME provides enterprise software solutions.">'
                "</head><body><h1>Welcome to ACME</h1>"
                "<p>Leading provider of business software since 2010.</p>"
                "<a href='/products'>Products</a><a href='/contact'>Contact</a></body></html>",
            )

        result = await probe_competitor_url(
            "https://www.acme-tools.com/", fetch=fetch_different_company, expected_name="OpenClaw"
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "wrong_company")

    async def test_hermes_com_403_rejected_as_unverified(self):
        """hermes.com returns 403 with minimal body - rejected as unverified."""
        from mvp.competitor_urls import probe_competitor_url

        async def fetch_hermes_403(url):
            return 403, url, "Access Denied"

        result = await probe_competitor_url(
            "https://www.hermes.com/", fetch=fetch_hermes_403, expected_name="Hermes Agent"
        )
        self.assertFalse(result.ok)
        # The host "hermes.com" brand is "hermes" which doesn't match "Hermes Agent",
        # and the body is too short, so it's rejected as unverified.
        self.assertIn("blocked_403", result.reason)

    async def test_glitch_farewell_journey_body_rejected(self):
        """glitch.com redirecting to farewell page with 'incredible journey' is defunct."""
        from mvp.competitor_urls import probe_competitor_url

        async def fetch_glitch_farewell(url):
            return (
                200,
                "https://blog.glitch.com/post/farewell-to-glitch",
                "<html><head><title>Farewell to Glitch</title></head><body>"
                "<h1>A heartfelt goodbye from the Glitch team</h1>"
                "<p>It's been an incredible journey building Glitch with you.</p></body></html>",
            )

        result = await probe_competitor_url("https://glitch.com/", fetch=fetch_glitch_farewell)
        self.assertFalse(result.ok)
        # Body contains "incredible journey" which matches _DEFUNCT_RE
        self.assertEqual(result.reason, "defunct_page")

    async def test_cloud9_shutdown_notice_rejected(self):
        """Cloud9 showing 'we have shut down' is defunct."""
        from mvp.competitor_urls import probe_competitor_url

        async def fetch_cloud9_shutdown(url):
            return (
                200,
                url,
                "<html><head><title>Cloud9 IDE</title></head><body>"
                "<h1>Cloud9 IDE</h1><p>Thank you for being part of our journey. "
                "We have shut down Cloud9 as a standalone service. "
                "Your workspaces have been migrated to AWS Cloud9.</p></body></html>",
            )

        result = await probe_competitor_url("https://c9.io/", fetch=fetch_cloud9_shutdown)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "defunct_page")

    async def test_parked_403_rejected(self):
        """A 403 with 'domain for sale' is parked, not blocked."""
        from mvp.competitor_urls import probe_competitor_url

        async def fetch_parked_403(url):
            return (
                403,
                url,
                "<html><head><title>Domain For Sale</title></head><body>"
                "<h1>This domain is for sale</h1><p>Buy this domain at GoDaddy auctions.</p></body></html>",
            )

        result = await probe_competitor_url("https://example-tool.com/", fetch=fetch_parked_403)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "defunct_page")

    async def test_openclaw_ai_accepted(self):
        """openclaw.ai is the real OpenClaw AI assistant."""
        from mvp.competitor_urls import probe_competitor_url

        async def fetch_openclaw_ai(url):
            return (
                200,
                url,
                "<html><head><title>OpenClaw — Open-Source AI Assistant</title>"
                '<meta name="description" content="OpenClaw is an open-source AI assistant '
                'that helps you automate tasks and build intelligent workflows.">'
                "</head><body><h1>OpenClaw AI</h1>"
                "<p>Build intelligent workflows with OpenClaw's AI agents. "
                "Connect to APIs, automate repetitive tasks, and deploy AI assistants.</p>"
                "<a href='/docs'>Documentation</a><a href='/pricing'>Pricing</a></body></html>",
            )

        result = await probe_competitor_url(
            "https://openclaw.ai/", fetch=fetch_openclaw_ai, expected_name="OpenClaw"
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "ok")

    async def test_hermes_agent_nousresearch_accepted(self):
        """hermes-agent.nousresearch.com is the real Hermes AI agent."""
        from mvp.competitor_urls import probe_competitor_url

        async def fetch_hermes_agent(url):
            return (
                200,
                url,
                "<html><head><title>Hermes Agent by Nous Research</title>"
                '<meta name="description" content="Hermes is an advanced AI agent from Nous Research '
                'for task automation and intelligent assistance.">'
                "</head><body><h1>Hermes Agent</h1>"
                "<p>Hermes is Nous Research's flagship AI agent, designed for complex task automation. "
                "Deploy intelligent agents that can browse the web, write code, and interact with APIs.</p>"
                "<a href='/try'>Try Hermes</a><a href='/docs'>Documentation</a></body></html>",
            )

        result = await probe_competitor_url(
            "https://hermes-agent.nousresearch.com/", fetch=fetch_hermes_agent, expected_name="Hermes"
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "ok")

    async def test_403_with_body_matching_product_accepted(self):
        """A 403 that shows product branding in the body is alive."""
        from mvp.competitor_urls import probe_competitor_url

        async def fetch_replit_403(url):
            return (
                403,
                url,
                "<html><head><title>Replit - Build software faster</title>"
                '<meta name="description" content="Replit is an AI-powered IDE where you can code, collaborate, and deploy.">'
                "</head><body><h1>Access limited</h1>"
                "<p>Replit is experiencing high traffic. Please try again later.</p></body></html>",
            )

        result = await probe_competitor_url(
            "https://replit.com/", fetch=fetch_replit_403, expected_name="Replit"
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "blocked_403")

    async def test_farewell_in_path_not_in_body_still_detected(self):
        """A redirect to a farewell URL path triggers rejection even if body is generic."""
        from mvp.competitor_urls import probe_competitor_url

        async def fetch_farewell_path(url):
            return (
                200,
                "https://blog.example.com/announcements/farewell-and-thank-you",
                "<html><head><title>Important Announcement</title></head><body>"
                "<h1>An update from our team</h1><p>Read our latest news.</p></body></html>",
            )

        result = await probe_competitor_url("https://example.com/", fetch=fetch_farewell_path)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "farewell_redirect")

    async def test_no_longer_available_to_new_customers_rejected(self):
        """A page saying 'no longer available to new customers' is defunct."""
        from mvp.competitor_urls import probe_competitor_url

        async def fetch_retired_service(url):
            return (
                200,
                url,
                "<html><head><title>Legacy Service</title></head><body>"
                "<h1>Service Update</h1>"
                "<p>This service is no longer available to new customers. "
                "Existing customers can continue to use their accounts until December 2026.</p></body></html>",
            )

        result = await probe_competitor_url("https://legacy.example.com/", fetch=fetch_retired_service)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "defunct_page")


if __name__ == "__main__":
    unittest.main()
