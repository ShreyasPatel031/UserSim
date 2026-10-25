"""Discovery agent (part 1): page parsing, Product Hunt parsing, and one full run with every source faked."""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest import mock

from mvp import discovery as D

HOME = """<html><head><title>Acme Boards — visual planning</title>
<meta name="description" content="Plan projects on shared boards."></head>
<body><script>var x=1</script><a href="/pricing">Pricing</a><a href="https://acme.io/about/">About</a>
<a href="https://other.com/pricing">x</a><h1>Boards for teams</h1></body></html>"""


def fake_llm(log):
    async def llm(messages):
        prompt = messages[-1]["content"]
        log.append(prompt)
        if "Return JSON:\n{\"name\"" in prompt:
            return json.dumps({"name": "Acme Boards", "one_liner": "Shared planning boards", "category": "project management",
                               "target_users": ["small teams"], "key_features": ["boards"], "search_terms": ["kanban app"],
                               "ph_topics": ["Productivity"]})
        if "\"candidates\"" in prompt:
            return json.dumps({"candidates": [
                {"name": "Acme Boards", "url": "https://acme.io", "why": "itself"},
                {"name": "Trello", "url": "https://trello.com", "why": "boards", "source": "web", "review_name": "Trello"},
                {"name": "DeadCo", "url": "https://dead.example", "why": "gone"},
                {"name": "Asana", "url": "asana.com", "why": "tasks", "source": "producthunt", "ph_slug": "asana"},
                {"name": "Monday", "url": "https://monday.com", "why": "work os"}]})
        return json.dumps({"segments": [{"id": "s1", "name": "Team leads", "evidence": ["u0", "u1"]},
                                        {"id": "s2", "name": "Made up", "evidence": ["u999"]}],
                           "tasks": [{"id": "t1", "title": "Create a board", "prompt": "Make a board", "segment_id": "s1"}]})
    return llm


class ParseTest(unittest.TestCase):
    def test_parse_page_keeps_same_site_subpages_and_strips_scripts(self):
        p = D.parse_page("https://acme.io/", HOME)
        self.assertEqual(p["title"], "Acme Boards — visual planning")
        self.assertEqual(p["description"], "Plan projects on shared boards.")
        self.assertEqual(p["subpages"], ["https://acme.io/pricing", "https://acme.io/about"])
        self.assertNotIn("var x", p["text"])

    def test_ph_users_drop_redacted_names_and_short_comments(self):
        node = {"comments": {"edges": [
            {"node": {"body": "Love it, switched from Trello because of the timeline view.", "votesCount": 3,
                      "user": {"name": "[REDACTED]", "headline": "PM at Foo", "username": "[REDACTED]"}}},
            {"node": {"body": "Congrats!", "user": {"name": "Bob"}}}]}}
        users = D._ph_users(node, "Acme")
        self.assertEqual(len(users), 1)
        self.assertEqual((users[0]["name"], users[0]["role"], users[0]["source"]), (None, "PM at Foo", "producthunt"))

    def test_parse_ddg_unwraps_links_and_keeps_snippets(self):
        html = ('<div class="result results_links web-result"><a rel="nofollow" class="result__a" '
                'href="//duckduckgo.com/l/?uddg=https%3A%2F%2Falternativeto.net%2Fsoftware%2Flinear%2F&amp;rut=x">Linear '
                '<b>Alternatives</b></a><a class="result__snippet" href="x">Top 12 tools like Linear</a></div>')
        self.assertEqual(D.parse_ddg(html, 5), [{"title": "Linear Alternatives", "url": "https://alternativeto.net/software/linear/",
                                                 "snippet": "Top 12 tools like Linear"}])

    def test_ph_bearer_prefers_developer_token(self):
        with mock.patch.dict(os.environ, {"PH_TOKEN": "dev", "PH_CLIENT_ID": "id", "PH_CLIENT_SECRET": "s"}):
            self.assertTrue(D.ph_configured())
            self.assertEqual(asyncio.run(D.ph_bearer()), "dev")
        with mock.patch.dict(os.environ, {"PH_TOKEN": "", "PH_CLIENT_ID": "id", "PH_CLIENT_SECRET": ""}):
            self.assertFalse(D.ph_configured())


class RunTest(unittest.TestCase):
    def _agent(self, *, ph=True, apify=True, reviews=None):
        run = D.new_run("acme.io", max_competitors=2, task_count=1)
        log = []
        a = D.DiscoveryAgent(run, llm=fake_llm(log))

        async def fetch(url):
            return 200, url, HOME

        async def search(q):
            return [{"title": f"{q} result", "url": "https://g2.com/x", "snippet": "Trello, Asana"}]

        async def post(slug):
            return {"name": "Asana", "slug": "asana", "tagline": "t", "topics": {"edges": []},
                    "comments": {"edges": [{"node": {"body": "We moved our whole agency to it last year.", "user": {"headline": "Ops lead"}}}]}} \
                if slug == "asana" else None

        async def topics(q):
            return [{"name": "Productivity", "slug": "productivity"}]

        async def topic_posts(t):
            return [{"name": "Asana", "slug": "asana", "tagline": "t", "votesCount": 9, "topics": ["productivity"]}]

        async def probe(url):
            return (False, "dns") if "dead" in url else (True, url.rstrip("/") + "/")

        a.fetch_html, a.web_search, a.ph_post_by_slug, a.ph_topics, a.ph_topic_posts, a.probe = fetch, search, post, topics, topic_posts, probe
        a.ph_configured = lambda: ph
        a.apify_token = lambda: "tok" if apify else None
        scraped = []

        def fetch_reviews(name):
            scraped.append(name)
            return (reviews or {}).get(name, {"reviews": [], "errors": []})
        a.fetch_reviews = fetch_reviews
        return a, log, scraped

    def test_full_run_picks_live_rivals_and_collects_users(self):
        rows = [{"source": "g2", "product": "Trello", "role": "Designer", "rating": 4, "pros": "easy", "cons": "slow"}] * 40
        a, log, scraped = self._agent(reviews={"Trello": {"reviews": rows, "errors": []}})
        run = asyncio.run(a.go())
        self.assertEqual(run.status, "done", run.error)
        r = run.result
        self.assertEqual([c["name"] for c in r["competitors"]], ["Trello", "Asana"])  # itself skipped, DeadCo dropped
        self.assertEqual(r["competitors"][1]["url"], "https://asana.com/")
        self.assertEqual(sorted(scraped), ["Acme Boards", "Asana", "Trello"])  # 40 reviews: no extra similar products
        self.assertEqual(r["counts"]["reviews"], 40)
        self.assertEqual(r["counts"]["ph_commenters"], 1)
        self.assertEqual(r["users"][0]["text"], "Liked: easy / Disliked: slow")
        self.assertEqual(r["tasks"][0]["title"], "Create a board")
        kinds = {s.kind for s in run.steps}
        self.assertTrue({"fetch", "search", "llm", "producthunt", "probe", "reviews"} <= kinds)
        self.assertIn("[u0] (g2 / Trello) role: Designer", log[-1])
        self.assertEqual([(g["name"], g["evidence"]) for g in r["segments"]], [("Team leads", ["u0", "u1"])])  # u999 backs nothing
        self.assertEqual([g["source"] for g in r["source_gaps"]],
                         ["G2 / Capterra reviews of Acme Boards", "G2 / Capterra reviews of Asana"])  # no reviews found

    def test_few_reviews_pull_in_similar_products(self):
        a, _, scraped = self._agent()
        run = asyncio.run(a.go())
        self.assertEqual(run.status, "done", run.error)
        self.assertEqual(scraped[3:], ["Monday"])  # DeadCo is dead, not a similar product

    def test_missing_tokens_skip_sources_and_still_finish(self):
        a, log, scraped = self._agent(ph=False, apify=False)
        run = asyncio.run(a.go())
        self.assertEqual(run.status, "done", run.error)
        skipped = [s.summary for s in run.steps if s.status == "skipped"]
        self.assertEqual(skipped, ["PH_TOKEN (or PH_CLIENT_ID + PH_CLIENT_SECRET) is not set", "APIFY_TOKEN is not set"])
        self.assertEqual(scraped, [])
        self.assertIn("No real users were retrieved, so write no user segments", log[-1])
        self.assertEqual(run.result["segments"], [])  # the fake LLM returns segments anyway: they are not kept
        self.assertEqual(run.result["tasks"][0]["title"], "Create a board")
        self.assertEqual(run.result["tasks"][0]["segment_id"], "")  # no segment to point at
        self.assertEqual([g["status"] for g in run.result["source_gaps"]], ["skipped", "skipped"])


if __name__ == "__main__":
    unittest.main()
