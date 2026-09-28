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
    # Keyword "Zapier alternative" is SEO. The page's own comparison is OpenClaw / Hermes.
    read = page_read_from_html(ZO_LIKE)
    about = read["about"]
    assert "A personal cloud server with AI" in about
    assert "scheduled AI agents" in about
    assert "The site compares itself with: OpenClaw, Hermes" in about
    assert "compares itself with: Zapier" not in about
    assert "Zapier alternative" in about
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


class WrongCategoryTests(unittest.TestCase):
    """A rival list drawn from SEO 'X alternative' keywords must not start browsers."""

    def test_like_needs_two_names_and_keyword_alternatives_stay_out_of_the_comparison(self):
        from mvp.fast_plan import _keyword_alternatives, _site_named_rivals

        text = "You can connect providers like Codex. Is Zo like OpenClaw or Hermes? Traditional vector databases like Pinecone and Qdrant need a round trip."
        self.assertEqual(_site_named_rivals("Zapier alternative", text), ["OpenClaw", "Hermes", "Pinecone", "Qdrant"])
        self.assertEqual(
            _keyword_alternatives("Zapier alternative,n8n alternative,ChatGPT alternative"),
            ["Zapier", "n8n", "ChatGPT"],
        )

    def test_product_copy_reaches_the_planner_ahead_of_the_quote_wall(self):
        # The 1500-char prompt used to be testimonials, so the FAQ never arrived.
        from mvp.fast_plan import prompt_text

        read = page_read_from_html(QUOTE_WALL)
        text = prompt_text(read)
        self.assertIn("always-on agent", text)
        self.assertIn("Customer quotes", text)
        self.assertLess(text.find("always-on agent"), text.find("Customer quotes"))
        self.assertIn("compares itself with: OpenClaw, Hermes", text)
        self.assertNotIn("compares itself with: Zapier", text)

    def test_seo_alternative_rivals_fail_closed_before_browsers(self):
        from mvp.fast_plan import category_conflict, plan_blocks_study, reject_study_plan

        read = page_read_from_html(QUOTE_WALL)
        names = {
            "https://zapier.com/": "Zapier",
            "https://n8n.io/": "n8n",
            "https://openclaw.ai/": "OpenClaw",
            "https://hermes-agent.nousresearch.com/": "Hermes",
            "https://manus.im/": "Manus",
        }
        reason = category_conflict(read, ["https://zapier.com/", "https://n8n.io/"], names)
        self.assertIn("OpenClaw", reason)
        self.assertIn("Zapier", reason)
        self.assertEqual(
            category_conflict(read, ["https://openclaw.ai/", "https://hermes-agent.nousresearch.com/"], names), ""
        )
        # A same-job rival the page does not name is kept when it is not an SEO alternative.
        self.assertEqual(category_conflict(read, ["https://openclaw.ai/", "https://manus.im/"], names), "")
        plan = {"rejected": reason, "competitors": ["https://zapier.com/", "https://n8n.io/"]}
        self.assertTrue(plan_blocks_study(plan))
        self.assertFalse(plan_blocks_study({"competitors": ["https://openclaw.ai/"]}))
        study = type("S", (), {"competitors": ["https://zapier.com/"], "early_runs": {}, "status": "queued", "error": None, "phase": ""})()
        self.assertTrue(reject_study_plan(study, plan))
        self.assertEqual(study.competitors, [])
        self.assertTrue(study.plan_rejected)
        self.assertEqual(study.status, "error")
        self.assertIn("OpenClaw", study.error)

    def test_javascript_bounce_is_not_a_homepage_and_the_brand_tld_is_recovered(self):
        import asyncio

        from mvp.competitor_urls import probe_competitor_url
        from mvp.fast_plan import settle_rival_urls

        async def fetch(url):
            return (
                200,
                url,
                "<!DOCTYPE html><html><head><script>window.onload=function(){window.location.href=\"/lander\"}</script></head></html>",
            )

        bounced = asyncio.run(probe_competitor_url("https://astrocade.xyz/", fetch=fetch))
        self.assertFalse(bounced.ok)
        self.assertEqual(bounced.reason, "thin_page")

        queries: list[str] = []

        async def probe(urls, product_url, exclude_hosts=None, limit=2):
            del product_url
            live, dropped = [], []
            blocked = set(exclude_hosts or [])
            for url in urls:
                host = url.split("/")[2].removeprefix("www.")
                if host in blocked:
                    continue
                if host in {"astrocade.xyz", "astrocade.ai"}:
                    dropped.append((url, "thin_page" if host.endswith(".xyz") else "redirected_off_site:forsale.example"))
                    continue
                if host == "latentlabs.ai":
                    dropped.append((url, "redirected_off_site:forsale.dynadot.com"))
                    continue
                live.append(url if url.endswith("/") else url + "/")
                blocked.add(host)
                if len(live) >= limit:
                    break
            return live, dropped

        async def search(query):
            queries.append(query)
            if "astrocade" in query.lower():
                return [("https://www.astrocade.com/", "Play Free Online Games or Create Your Own with AI | Astrocade")]
            return [("https://www.latentlabs.com/", "Latent Labs")]

        read = {"compared_with": [], "keyword_alts": []}
        landed, names, _remap, reason = asyncio.run(
            settle_rival_urls(
                "https://chatforce.com/",
                "Chatforce",
                [("https://rosebud.ai/", "Rosebud AI"), ("https://astrocade.xyz/", "Astrocade")],
                read,
                limit=2,
                probe=probe,
                search=search,
            )
        )
        self.assertEqual(reason, "")
        self.assertEqual(landed, ["https://rosebud.ai/", "https://www.astrocade.com/"])
        self.assertEqual(names["https://www.astrocade.com/"], "Astrocade")
        # A for-sale redirect is not replaced via brand search (the name may be a different company).
        # But invent_competitors is called as a fallback to find more same-job rivals.
        queries.clear()
        from unittest import mock

        async def mock_invent(*args, **kwargs):
            return []

        with mock.patch("mvp.study.invent_competitors", mock_invent):
            landed, _names, _remap, reason = asyncio.run(
                settle_rival_urls(
                    "https://chatforce.com/",
                    "Chatforce",
                    [("https://rosebud.ai/", "Rosebud"), ("https://latentlabs.ai/", "Latent Labs")],
                    read,
                    limit=2,
                    probe=probe,
                    search=search,
                )
            )
        self.assertIn("only 1 live", reason)
        self.assertEqual(queries, [])
        # A dead guess's buyers follow the live backup that took its slot, not the dead URL.
        landed, names, remap, reason = asyncio.run(
            settle_rival_urls(
                "https://chatforce.com/",
                "Chatforce",
                [
                    ("https://rosebud.ai/", "Rosebud"),
                    ("https://astrocade.ai/", "Astrocade"),
                    ("https://ludo.ai/", "Ludo"),
                ],
                read,
                limit=2,
                probe=probe,
                search=search,
            )
        )
        self.assertEqual(reason, "")
        self.assertEqual(landed, ["https://rosebud.ai/", "https://ludo.ai/"])
        self.assertEqual(remap["https://astrocade.ai/"], "https://ludo.ai/")

    def test_comparison_roundup_is_not_a_play_page_or_an_seo_alternative(self):
        from mvp.fast_plan import comparison_article_url

        locs = [
            "https://chatforce.com/play/cats-vs-zombies",
            "https://chatforce.com/alternative-to-cursor",
            "https://chatforce.com/alternative-to-rosebud",
            "https://chatforce.com/blog/best-ai-game-makers-compared",
            "https://example.com/blog/best-compared",
        ]
        self.assertEqual(
            comparison_article_url(locs, "chatforce.com"),
            "https://chatforce.com/blog/best-ai-game-makers-compared",
        )
        self.assertEqual(comparison_article_url(["https://www.zo.computer/pricing"], "zo.computer"), "")

    def test_dead_guess_resolves_to_the_page_named_homepage_and_skips_seo_alts(self):
        from mvp.fast_plan import settle_rival_urls

        read = page_read_from_html(QUOTE_WALL)
        probed: list[str] = []

        async def probe(urls, product_url, exclude_hosts=None, limit=2):
            del product_url
            probed.extend(urls)
            dead = {"https://www.openclaw.com/", "https://hermes.ai/"}
            live, dropped = [], []
            blocked = set(exclude_hosts or [])
            for url in urls:
                host = url.split("/")[2].removeprefix("www.")
                if url in dead:
                    dropped.append((url, "redirected_off_site:domains.atom.com"))
                    continue
                if host in blocked:
                    dropped.append((url, "duplicate_or_product_host"))
                    continue
                live.append(url if url.endswith("/") else url + "/")
                blocked.add(host)
                if len(live) >= limit:
                    break
            return live, dropped

        async def search(query):
            q = query.lower()
            if q.startswith("openclaw"):
                return [("https://openclaw.ai/", "OpenClaw — Open-Source AI Assistant")]
            if "hermes" in q:
                return [
                    ("https://openclaw.ai/", "OpenClaw — Open-Source AI Assistant"),
                    ("https://hermes-agent.nousresearch.com/", "Hermes Agent"),
                ]
            return []

        import asyncio

        landed, names, remap, reason = asyncio.run(
            settle_rival_urls(
                "https://www.zo.computer/",
                "Zo Computer",
                [
                    ("https://www.openclaw.com/", "OpenClaw"),
                    ("https://hermes.ai/", "Hermes"),
                    ("https://zapier.com/", "Zapier"),
                ],
                read,
                limit=2,
                probe=probe,
                search=search,
            )
        )
        self.assertEqual(reason, "")
        self.assertEqual(landed, ["https://openclaw.ai/", "https://hermes-agent.nousresearch.com/"])
        self.assertEqual(names["https://openclaw.ai/"], "OpenClaw")
        self.assertEqual(names["https://hermes-agent.nousresearch.com/"], "Hermes")
        self.assertEqual(remap["https://www.openclaw.com/"], "https://openclaw.ai/")
        self.assertNotIn("https://zapier.com/", probed)

    def test_named_vector_databases_are_not_a_keyword_conflict(self):
        from mvp.fast_plan import category_conflict

        html = """<html><head><title>Moss</title>
<meta name="keywords" content="semantic search, vector search"/></head>
<body><p>Traditional vector databases like Pinecone and Qdrant require a cloud round trip.</p></body></html>"""
        read = page_read_from_html(html)
        self.assertEqual(read["compared_with"], ["Pinecone", "Qdrant"])
        self.assertEqual(read["keyword_alts"], [])
        self.assertEqual(
            category_conflict(
                read,
                ["https://www.pinecone.io/", "https://qdrant.tech/"],
                {"https://www.pinecone.io/": "Pinecone", "https://qdrant.tech/": "Qdrant"},
            ),
            "",
        )


QUOTE_WALL = """<html><head><title>Zo Computer</title>
<meta name="description" content="A personal cloud computer that works 24/7"/>
<meta name="keywords" content="Zapier alternative,n8n alternative,ChatGPT alternative"/>
</head><body>
<h1>Build something seriously powerful</h1>
<p>“ """ + ("I built a 3D portfolio website on Zo and left Webflow behind for good. " * 40) + """”</p>
<p>Is Zo like OpenClaw or Hermes? Unlike OpenClaw or Hermes, Zo is a personal cloud computer with an always-on agent. No terminal setup.</p>
</body></html>"""


class KeywordAlternativeKeptTests(unittest.TestCase):
    """Keyword alternatives are kept when the page names no explicit rivals."""

    def test_keyword_only_returns_false_when_compared_is_empty(self):
        from mvp.fast_plan import _keyword_only_name

        read_with_comparisons = {"compared_with": ["OpenClaw", "Hermes"], "keyword_alts": ["Zapier", "n8n"]}
        self.assertTrue(_keyword_only_name("Zapier", read_with_comparisons))
        self.assertFalse(_keyword_only_name("OpenClaw", read_with_comparisons))
        read_no_comparisons = {"compared_with": [], "keyword_alts": ["Zapier", "n8n", "Make"]}
        self.assertFalse(_keyword_only_name("Zapier", read_no_comparisons))
        self.assertFalse(_keyword_only_name("n8n", read_no_comparisons))

    def test_zapier_alternative_keeps_keyword_rivals_when_page_names_none(self):
        import asyncio

        from mvp.fast_plan import settle_rival_urls

        async def probe(urls, product_url, exclude_hosts=None, limit=2):
            del product_url
            live, dropped = [], []
            blocked = set(exclude_hosts or [])
            for url in urls:
                host = url.split("/")[2].removeprefix("www.")
                if host in blocked:
                    continue
                live.append(url if url.endswith("/") else url + "/")
                blocked.add(host)
                if len(live) >= limit:
                    break
            return live, dropped

        read = {"compared_with": [], "keyword_alts": ["Zapier", "n8n", "Make"]}
        landed, names, _remap, reason = asyncio.run(
            settle_rival_urls(
                "https://www.activepieces.com/",
                "Activepieces",
                [("https://zapier.com/", "Zapier"), ("https://n8n.io/", "n8n"), ("https://make.com/", "Make")],
                read,
                limit=2,
                probe=probe,
            )
        )
        self.assertEqual(reason, "")
        self.assertEqual(landed, ["https://zapier.com/", "https://n8n.io/"])
        self.assertEqual(names["https://zapier.com/"], "Zapier")


class BotBlockedTreatedAsLiveTests(unittest.TestCase):
    """A 403 or 429 response means the site is alive but blocking the probe."""

    def test_403_is_kept_as_live_but_blocked(self):
        import asyncio

        from mvp.competitor_urls import probe_competitor_url

        async def fetch_403(url):
            return 403, url, "Forbidden"

        result = asyncio.run(probe_competitor_url("https://replit.com/", fetch=fetch_403))
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "blocked_403")
        self.assertEqual(result.url, "https://replit.com/")

    def test_429_is_kept_as_live_but_blocked(self):
        import asyncio

        from mvp.competitor_urls import probe_competitor_url

        async def fetch_429(url):
            return 429, url, "Too Many Requests"

        result = asyncio.run(probe_competitor_url("https://example.com/", fetch=fetch_429))
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "blocked_429")
        self.assertEqual(result.url, "https://example.com/")

    def test_403_with_offsite_redirect_is_rejected(self):
        """A 403 that redirected off-site (e.g. to a domain seller) is NOT accepted."""
        import asyncio

        from mvp.competitor_urls import probe_competitor_url

        async def fetch_403_redirect(url):
            return 403, "https://forsale.dynadot.com/", "Forbidden"

        result = asyncio.run(probe_competitor_url("https://example.com/", fetch=fetch_403_redirect))
        self.assertFalse(result.ok)
        self.assertIn("redirected_off_site", result.reason)

    def test_blocked_rival_does_not_stop_the_study(self):
        import asyncio

        from mvp.fast_plan import settle_rival_urls

        async def probe(urls, product_url, exclude_hosts=None, limit=2):
            del product_url
            live, dropped = [], []
            blocked = set(exclude_hosts or [])
            for url in urls:
                host = url.split("/")[2].removeprefix("www.")
                if host in blocked:
                    continue
                live.append(url if url.endswith("/") else url + "/")
                blocked.add(host)
                if len(live) >= limit:
                    break
            return live, dropped

        read = {"compared_with": [], "keyword_alts": []}
        landed, names, _remap, reason = asyncio.run(
            settle_rival_urls(
                "https://www.cursor.com/",
                "Cursor",
                [("https://replit.com/", "Replit"), ("https://github.com/codespaces", "Codespaces")],
                read,
                limit=2,
                probe=probe,
            )
        )
        self.assertEqual(reason, "")
        self.assertEqual(len(landed), 2)
