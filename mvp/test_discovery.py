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

    def test_review_page_takes_the_matching_product_only(self):
        rows = [{"url": "https://www.g2.com/products/acme-anvils/reviews"}, {"url": "https://www.g2.com/products/jira/reviews?x=1"}]
        self.assertEqual(D.review_page(rows, "g2", "Jira")[0], "https://www.g2.com/products/jira/reviews")
        self.assertEqual(D.review_page(rows[:1], "g2", "Jira")[0], None)  # acme-anvils is another product
        cap = [{"url": "https://www.capterra.com/p/19319/JIRA/reviews/"}]
        self.assertEqual(D.review_page(cap, "capterra", "Jira")[0], "https://www.capterra.com/p/19319/JIRA/")

    def test_review_page_rejects_longer_product_names(self):
        rows = [{"url": "https://www.g2.com/products/jira-service-management/reviews"}]
        self.assertEqual(D.review_page(rows, "g2", "Jira")[0], None)
        self.assertEqual(D.review_page([{"url": "https://www.g2.com/products/linear-2/reviews"}], "g2", "Linear")[0],
                         "https://www.g2.com/products/linear-2/reviews")
        self.assertEqual(D.review_page([{"url": "https://www.capterra.com/p/1/Vimeo-Pro/"}], "capterra", "Vimeo")[0],
                         "https://www.capterra.com/p/1/Vimeo-Pro/")
        self.assertIsNone(D.review_page([{"url": "https://www.g2.com/products/youtube-live/reviews"}], "g2", "YouTube")[0])
        ph = [{"url": "https://www.producthunt.com/products/linear-agent"}, {"url": "https://www.producthunt.com/products/linear/reviews"}]
        self.assertEqual(D.review_page(ph, "producthunt", "Linear")[0], "https://www.producthunt.com/products/linear/reviews")


class RunTest(unittest.TestCase):
    HOMES = {"Trello": "trello.com", "Asana": "asana.com", "DeadCo": "dead.example", "Monday": "monday.com"}

    def _agent(self, *, ph=True, apify=True, reviews=None):
        run = D.new_run("acme.io", max_competitors=2, task_count=1)
        log, searched, scraped = [], [], []
        a = D.DiscoveryAgent(run, llm=fake_llm(log))

        async def fetch(url):
            return 200, url, HOME

        def one(q):
            if q == "site:producthunt.com Asana reviews":
                return [{"title": "Asana", "url": "https://www.producthunt.com/products/asana"}]
            if q == "site:g2.com Trello reviews":
                return [{"title": "Trello reviews", "url": "https://www.g2.com/products/trello/reviews?page=2"}]
            if q == "site:capterra.com Trello reviews":
                return [{"title": "Trello", "url": "https://www.capterra.com/p/72290/Trello/reviews/"}]
            if q == "site:g2.com Acme Boards reviews":
                return [{"title": "Acme Anvils", "url": "https://www.g2.com/products/acme-anvils/reviews"}]
            if q.startswith("site:"):
                return []
            for name, host in self.HOMES.items():
                if q.startswith(name + " "):
                    return [{"title": name, "url": f"https://www.{host}/"}, {"title": "x", "url": "https://www.g2.com/compare"}]
            return [{"title": f"{q} result", "url": "https://g2.com/x", "snippet": "Trello, Asana"}]

        async def search_many(qs, model=None):
            searched.extend(qs)
            return {q: one(q) for q in qs}

        async def topics(q):
            return [{"name": "Productivity", "slug": "productivity"}]

        async def topic_posts(t):
            return [{"name": "Asana", "slug": "asana", "tagline": "t", "votesCount": 9, "topics": ["productivity"]}]

        async def probe(url):
            return (False, "dns") if "dead" in url else (True, url.rstrip("/") + "/")

        def scrape(platform, url, product=""):
            scraped.append(url)
            return (reviews or {}).get(url, [])

        a.fetch_html, a.web_search_many, a.ph_topics, a.ph_topic_posts, a.probe = fetch, search_many, topics, topic_posts, probe
        async def grounded(prompt, model=None):
            return '{"competitors": [{"name": "Trello", "homepage": "https://trello.com"}]}'
        a.grounded_answer = grounded
        a.ph_configured = lambda: ph
        a.apify_token = lambda: "tok" if apify else None
        a.scrape_review_page = scrape
        return a, log, searched, scraped

    def test_full_run_takes_every_page_from_search(self):
        rows = [{"source": "g2", "role": "Designer", "rating": 4, "pros": "easy", "cons": "slow"}] * 40
        ph = [{"source": "producthunt", "name": "Ann", "role": "Ops lead", "text": "We moved our whole agency to it."}]
        a, log, searched, scraped = self._agent(reviews={"https://www.g2.com/products/trello/reviews": rows,
                                                         "https://www.producthunt.com/products/asana/reviews": ph})
        run = asyncio.run(a.go())
        self.assertEqual(run.status, "done", run.error)
        r = run.result
        self.assertEqual([c["name"] for c in r["competitors"]], ["Trello", "Asana"])  # itself skipped, DeadCo dead
        self.assertEqual(r["competitors"][1]["url"], "https://www.asana.com/")  # the Google result URL
        # exact pages from the search results, canonicalised; nothing scraped by guessed name
        self.assertEqual(sorted(scraped), ["https://www.capterra.com/p/72290/Trello/", "https://www.g2.com/products/trello/reviews",
                                           "https://www.producthunt.com/products/asana/reviews"])
        self.assertNotIn("site:g2.com Monday reviews", searched)  # 40 reviews: no extra similar products
        self.assertEqual(r["counts"]["reviews"], 40)
        self.assertEqual(r["counts"]["ph_reviewers"], 1)  # Asana's Product Hunt page, found via its producthunt.com URL
        self.assertTrue({"Acme Boards reviews on G2", "Acme Boards reviews g2.com", "site:g2.com Acme Boards reviews"} <= set(searched))
        self.assertEqual(r["users"][0]["text"], "Liked: easy / Disliked: slow")
        self.assertEqual(r["users"][0]["product"], "Trello")
        self.assertIn("[u0] (g2 / Trello) role: Designer", log[-1])
        self.assertIn("PRODUCTS BUYERS MOST OFTEN COMPARE IT WITH (Google-researched; the main evidence):\n- Trello (https://trello.com)",
                      next(p for p in log if '"candidates"' in p))
        self.assertEqual([(g["name"], g["evidence"]) for g in r["segments"]], [("Team leads", ["u0", "u1"])])  # u999 backs nothing
        gaps = {g["source"]: g["why"] for g in r["source_gaps"]}
        self.assertIn("other products: ['acme-anvils']", gaps["G2 reviews of Acme Boards"])
        self.assertEqual(r["users"][-1]["role"], "Ops lead")
        self.assertEqual(gaps["Capterra reviews of Asana"], "no capterra product page in the search results")

    def test_few_reviews_pull_in_similar_products(self):
        a, _, searched, _ = self._agent()
        run = asyncio.run(a.go())
        self.assertEqual(run.status, "done", run.error)
        self.assertIn("site:g2.com Monday reviews", searched)
        self.assertNotIn("site:g2.com DeadCo reviews", searched)  # dead site: not a similar product

    def test_missing_tokens_skip_sources_and_still_finish(self):
        a, log, searched, scraped = self._agent(ph=False, apify=False)
        run = asyncio.run(a.go())
        self.assertEqual(run.status, "done", run.error)
        skipped = [s.summary for s in run.steps if s.status == "skipped"]
        self.assertEqual(sorted(skipped), ["APIFY_TOKEN is not set", "PH_TOKEN (or PH_CLIENT_ID + PH_CLIENT_SECRET) is not set"])
        self.assertEqual(scraped, [])
        self.assertFalse([q for q in searched if q.startswith("site:")])
        self.assertIn("No real users were retrieved, so write no user segments", log[-1])
        self.assertEqual(run.result["segments"], [])  # the fake LLM returns segments anyway: they are not kept
        self.assertEqual(run.result["tasks"][0]["title"], "Create a board")
        self.assertEqual(run.result["tasks"][0]["segment_id"], "")  # no segment to point at
        self.assertEqual([g["status"] for g in run.result["source_gaps"]], ["skipped", "skipped"])

    def test_run_keys_are_used_for_that_run_only_and_never_saved(self):
        a, _, _, _ = self._agent(apify=True, ph=True)
        a.apify_token, a.ph_configured = D.apify_token, D.ph_configured  # the real credential lookups
        seen = []
        a.web_search_many = (lambda orig: (lambda qs, **kw: (seen.append((D.apify_token(), D.ph_configured())), orig(qs, **kw))[1]))(a.web_search_many)
        a._credentials = {"APIFY_TOKEN": "apify_api_RUNKEY123", "PH_TOKEN": "ph-run-key"}
        with mock.patch.dict(os.environ, {"APIFY_TOKEN": "", "PH_TOKEN": "", "PH_CLIENT_ID": "", "PH_CLIENT_SECRET": ""}), \
                mock.patch("mvp.review_context.apify_token", return_value=None):
            run = asyncio.run(a.go())
            self.assertIsNone(D.apify_token())  # outside the run: the server's (none here)
        self.assertEqual(run.status, "done", run.error)
        self.assertEqual(seen[0], ("apify_api_RUNKEY123", True))
        dumped = json.dumps(run.to_dict(), default=str)
        self.assertNotIn("RUNKEY123", dumped)
        self.assertNotIn("ph-run-key", dumped)


class GoogleSearchTest(unittest.TestCase):
    def test_grounding_links_are_resolved_to_real_pages_and_failures_fall_back_to_ddg(self):
        import types
        import httpx

        body = {"candidates": [{"groundingMetadata": {"groundingChunks": [
            {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA", "title": "g2.com"}},
            {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/BBB", "title": "g2.com"}},
            {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA", "title": "g2.com"}}]}}]}
        where = {"AAA": "https://www.g2.com/products/vimeo/reviews", "BBB": "https://www.g2.com/products/vimeo-ott/reviews"}

        async def post(self, url, json=None, headers=None):
            assert json["tools"] == [{"googleSearch": {}}]
            return httpx.Response(200, json=body, request=httpx.Request("POST", url))

        async def get(self, url, follow_redirects=True):
            return httpx.Response(302, headers={"location": where[url.rsplit("/", 1)[1]]}, request=httpx.Request("GET", url))

        creds = types.SimpleNamespace(token="t")
        with mock.patch.object(httpx.AsyncClient, "post", post), mock.patch.object(httpx.AsyncClient, "get", get), \
                mock.patch("auth.cached_vertex_credentials", return_value=creds), \
                mock.patch("capability.gemini_config._endpoint", return_value="https://vertex.invalid"):
            rows = asyncio.run(D.google_search("site:g2.com Vimeo reviews"))
        self.assertEqual([r["url"] for r in rows], [where["AAA"], where["BBB"]])  # resolved and de-duplicated

        async def boom(q, limit=8, model=None):
            raise RuntimeError("vertex down")

        async def ddg(q, limit=8):
            return [{"title": "x", "url": "https://x.com", "snippet": "", "engine": "duckduckgo"}]
        with mock.patch.object(D, "google_search", boom), mock.patch.object(D, "ddg_search", ddg):
            self.assertEqual(asyncio.run(D.web_search_many(["q"]))["q"][0]["engine"], "duckduckgo")


class SavedKeysTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        D._KEYS_FILE = None
        patcher = mock.patch.dict(os.environ, {"MVP_DISCOVERY_KEYS_FILE": os.path.join(self.dir.name, "keys.json"),
                                               "APIFY_TOKEN": "", "PH_TOKEN": "", "PH_CLIENT_ID": "", "PH_CLIENT_SECRET": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(setattr, D, "_KEYS_FILE", None)
        p2 = mock.patch("mvp.review_context.apify_token", return_value=None)
        p2.start()
        self.addCleanup(p2.stop)

    def test_saved_keys_are_used_and_only_replaceable_with_the_current_apify_key(self):
        self.assertFalse(D.keys_status()["APIFY_TOKEN"]["present"])
        self.assertEqual(D.save_keys({"APIFY_TOKEN": "apify_api_A", "PH_TOKEN": "ph1", "BOGUS": "x"}), (True, "saved"))
        self.assertEqual(oct(os.stat(D.keys_file()).st_mode & 0o777), "0o600")
        self.assertEqual((D.apify_token(), D.ph_configured()), ("apify_api_A", True))
        self.assertEqual(D.keys_status()["PH_TOKEN"], {"present": True, "source": "saved"})
        self.assertNotIn("apify_api_A", json.dumps(D.keys_status()))
        self.assertFalse(D.save_keys({"APIFY_TOKEN": "attacker"})[0])
        self.assertFalse(D.save_keys({"APIFY_TOKEN": "attacker"}, "wrong")[0])
        self.assertTrue(D.save_keys({"APIFY_TOKEN": "apify_api_B"}, "apify_api_A")[0])
        self.assertEqual(D.stored_keys(), {"APIFY_TOKEN": "apify_api_B", "PH_TOKEN": "ph1"})


if __name__ == "__main__":
    unittest.main()
