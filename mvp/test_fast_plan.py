"""Home-page planner: tasks only name what the opening page exposes."""

from __future__ import annotations

import unittest

from mvp.a11y_agent import action_label
from mvp.fast_plan import _links_for_prompt, choose_tasks, page_read_from_html, task_grounded
from mvp.report_insights import human_action

APP_SHELL = """<!doctype html><html><head><title>whiteboard • free whiteboard</title>
<meta name="description" content="A free online whiteboard."></head>
<body><div id="root"></div><script>window.boot()</script></body></html>"""

MARKETING = """<html><head><title>Plan your week | Planner</title></head><body>
<nav><a href="/features">Features</a><a href="/pricing">Pricing</a>
<a href="https://app.example.com/login">Log in</a><button aria-label="Open menu"></button>
<a href="/changelog">What&#39;s new</a></nav><h1>Plan your week</h1></body></html>"""

NO_PRICING = """<html><head><title>Docs tool</title></head><body>
<a href="/features">Features</a><a href="/blog">Blog</a><a href="/signup">Start free</a></body></html>"""


class PageReadTest(unittest.TestCase):
    def test_links_and_buttons_come_from_the_page(self):
        read = page_read_from_html(MARKETING)
        self.assertEqual(read["title"], "Plan your week | Planner")
        labels = [label for label, _ in read["links"]]
        self.assertIn("Pricing", labels)
        self.assertIn("Open menu", labels)  # aria-label of an icon button
        self.assertIn("What's new", labels)

    def test_client_rendered_app_exposes_no_links(self):
        read = page_read_from_html(APP_SHELL)
        self.assertEqual(read["links"], [])
        self.assertIn("free online whiteboard", read["text"])
        self.assertIn("no links", _links_for_prompt(read))


class GroundingTest(unittest.TestCase):
    def test_pricing_needs_a_pricing_link(self):
        task = "Look for pricing or how to get started"
        self.assertTrue(task_grounded(task, page_read_from_html(MARKETING)))
        self.assertFalse(task_grounded(task, page_read_from_html(APP_SHELL)))
        self.assertFalse(task_grounded(task, page_read_from_html(NO_PRICING)))

    def test_other_public_tasks_need_a_matching_link_or_text(self):
        self.assertTrue(task_grounded("Open the changelog", page_read_from_html(MARKETING)))
        self.assertFalse(task_grounded("Open the changelog", page_read_from_html(NO_PRICING)))


class ChooseTasksTest(unittest.TestCase):
    PLAN = {
        "core_task": "Draw a rectangle on the canvas",
        "public_task": "Look for pricing or how to get started",
        "app_task": "Add a text label that says hello",
    }

    def test_app_page_gets_a_second_in_app_task_not_pricing(self):
        self.assertEqual(
            choose_tasks(self.PLAN, page_read_from_html(APP_SHELL)),
            ["Draw a rectangle on the canvas", "Add a text label that says hello"],
        )

    def test_marketing_page_with_pricing_link_keeps_pricing(self):
        plan = dict(self.PLAN, public_task="Explore all the features")
        self.assertEqual(
            choose_tasks(plan, page_read_from_html(MARKETING))[1], "Look for pricing or how to get started"
        )

    def test_ungrounded_or_vague_public_task_falls_back_to_the_app_task(self):
        plan = dict(self.PLAN, public_task="Open the changelog")
        self.assertEqual(choose_tasks(plan, page_read_from_html(NO_PRICING))[1], "Add a text label that says hello")
        plan = dict(self.PLAN, public_task="Explore the blog")  # listed, but nothing to check at the end
        self.assertEqual(choose_tasks(plan, page_read_from_html(NO_PRICING))[1], "Add a text label that says hello")

    def test_account_core_task_is_kept_as_is(self):
        plan = dict(self.PLAN, core_task="Create a new issue in your workspace")
        tasks = choose_tasks(plan, page_read_from_html(MARKETING))
        self.assertEqual(tasks[0], "Create a new issue in your workspace")

    def test_unreadable_page_keeps_the_usual_pair(self):
        tasks = choose_tasks(self.PLAN, {"title": "", "text": "", "links": [], "failed": True})
        self.assertEqual(tasks, ["Draw a rectangle on the canvas", "Look for pricing or how to get started"])

    def test_old_reply_shape_still_works(self):
        tasks = choose_tasks({"tasks": ["Create a new project", "Look for pricing or how to get started"]}, page_read_from_html(MARKETING))
        self.assertEqual(tasks, ["Create a new project", "Look for pricing or how to get started"])


class StepLabelTest(unittest.TestCase):
    def test_drag_label_has_no_coordinates(self):
        self.assertEqual(action_label({"act": "drag", "text": "500,200"}), "drag on the canvas")
        self.assertEqual(human_action("drag 500,200"), "drag on the canvas")
        self.assertEqual(human_action("drag"), "drag on the canvas")

    def test_dom_ids_read_as_words(self):
        self.assertEqual(human_action("click main-menu-trigger"), "click main menu")
        self.assertEqual(human_action("click Pricing"), "click Pricing")
        self.assertEqual(human_action("type 'hello' into search_input"), "type 'hello' into search input")


if __name__ == "__main__":
    unittest.main()


class DirectCompetitorTests(unittest.TestCase):
    def test_suite_vendor_homepage_is_skipped_for_the_next_candidate(self):
        from mvp.fast_plan import _PROMPT, pick_competitors

        got = pick_competitors(["https://www.adobe.com/", "https://www.sketch.com/", "https://penpot.app/"], "figma.com")
        self.assertEqual(got, ["https://www.sketch.com/", "https://penpot.app/"])
        self.assertIn("Never a parent company", _PROMPT)

    def test_own_site_and_vendor_pages_are_not_rivals(self):
        from mvp.fast_plan import pick_competitors

        # Rival URLs are cut to the homepage, so a vendor's product page is the vendor.
        got = pick_competitors(["https://figma.com/", "https://www.microsoft.com/en-us/microsoft-teams/", "https://zoom.us/"], "figma.com")
        self.assertEqual(got, ["https://zoom.us/"])
