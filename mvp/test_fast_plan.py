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

        # A suite vendor's bare homepage is skipped; its product page keeps its path and is a candidate.
        got = pick_competitors(["https://figma.com/", "https://www.microsoft.com/", "https://aws.amazon.com/bedrock/?x=1", "https://zoom.us/"], "figma.com")
        self.assertEqual(got, ["https://aws.amazon.com/bedrock/", "https://zoom.us/"])


def test_connect_data_source_core_task_swapped_for_app_task():
    from mvp.fast_plan import choose_tasks, needs_customer_credentials

    assert needs_customer_credentials("Connect a product data source")
    assert needs_customer_credentials("Integrate your Stripe account")
    assert not needs_customer_credentials("See which accounts are at risk")
    assert not needs_customer_credentials("Add a link to the note")
    data = {"core_task": "Connect a product data source", "app_task": "See which accounts are at risk"}
    tasks = choose_tasks(data, {"links": [], "title": "Kolanut"})
    assert tasks[0] == "See which accounts are at risk"
    assert all(not needs_customer_credentials(t) for t in tasks)


def test_spliced_plan_never_repeats_a_persona_name():
    # Study 50f0954c: the early buyer and the full plan both invented "Alex Chen".
    from mvp.early_start import splice_plan

    plan = {
        "product": "Zo Computer",
        "personas": [
            {"name": "Joanna Lee", "favors": "product"},
            {"name": "Alex Chen", "favors": "https://replit.com/"},
            {"name": "Maria Rodriguez", "favors": "https://www.netlify.com/"},
            {"name": "David Lee", "favors": "https://vercel.com/"},
        ],
        "task_specs": [{"prompt": "Build a site", "favors": "product"}],
    }
    starter = {"persona": {"name": "Alex Chen", "favors": "product"}, "task": "Build a site"}
    names = [p["name"] for p in splice_plan(plan, starter)["personas"]]
    assert names[0] == "Alex Chen"  # the running early buyer keeps its name
    firsts = [n.split()[0] for n in names]
    lasts = [n.split()[-1] for n in names]
    assert len(set(firsts)) == len(names) and len(set(lasts)) == len(names), names


def test_persona_named_after_a_page_testimonial_is_renamed():
    from mvp.fast_plan import compare_personas

    read = page_read_from_html(
        '<html><body><a href="https://joannakurylo.zo.space/">joannakurylo.zo.space</a> Joanna says hi</body></html>'
    )
    data = {"personas": [{"name": "Joanna Kurylo", "favors": "product"}, {"name": "Sam Ortiz", "favors": "product"}]}
    names = [p["name"] for p in compare_personas(data, "zo.computer", [], {}, read)]
    assert "Joanna Kurylo" not in names and names[1] == "Sam Ortiz"


ZO_LIKE = """<html><head><title>Zo Computer | Build something seriously powerful</title>
<meta name="description" content="Run your business and life on Zo with a cloud computer that works 24/7"/>
<meta name="keywords" content="personal AI assistant,scheduled AI agents,Zapier alternative,n8n alternative"/>
<script type="application/ld+json">{"@graph":[{"@type":"SoftwareApplication","applicationCategory":"DeveloperApplication",
"description":"A personal cloud server with AI. Text it instructions, schedule agents, host sites."}]}</script></head>
<body><h1>Build something seriously powerful</h1><p>John: Zo made it easy to build my own 3D portfolio world.</p>
<p>Is Zo like OpenClaw or Hermes? Yes, and more.</p></body></html>"""


def test_about_line_carries_the_sites_own_positioning():
    # Study 50f0954c: the 800-char text was all website testimonials, so the plan
    # compared Zo (a personal AI cloud computer) with Replit, Netlify and Vercel.
    read = page_read_from_html(ZO_LIKE)
    about = read["about"]
    assert "A personal cloud server with AI" in about
    assert "scheduled AI agents" in about
    assert "The site compares itself with: Zapier, n8n, OpenClaw, Hermes" in about
    assert "3D portfolio" in read["full_text"]


def test_prompt_text_puts_about_first_only_with_the_read_fix(monkeypatch=None):
    import os

    from mvp.fast_plan import prompt_text, read_rule

    read = page_read_from_html(ZO_LIKE)
    old = os.environ.get("MVP_PLAN_FRAMING")
    try:
        os.environ["MVP_PLAN_FRAMING"] = "read"
        assert prompt_text(read).startswith("About: ")
        assert "showcase" in read_rule()
        os.environ["MVP_PLAN_FRAMING"] = "off"
        assert prompt_text(read) == read["text"][:800]
        assert read_rule() == ""
    finally:
        if old is None:
            os.environ.pop("MVP_PLAN_FRAMING", None)
        else:
            os.environ["MVP_PLAN_FRAMING"] = old


def test_named_rivals_skip_pronouns_and_lowercase_mentions():
    from mvp.fast_plan import _site_named_rivals

    got = _site_named_rivals("", "Better than the rest. Unlike Notion or Coda. something I could never do on webflow or wordpress")
    assert got == ["Notion", "Coda"]
