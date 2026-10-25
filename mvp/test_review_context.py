"""Competitor review evidence: product matching, opt-out, background-only live scrapes, feedback prompt wiring."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mvp import review_context as R


class ReviewContextTest(unittest.TestCase):
    def test_same_product_rejects_other_search_hits(self):
        self.assertTrue(R._same_product("Trello", "trello"))
        self.assertTrue(R._same_product("Zoho CRM", "Zoho"))
        self.assertFalse(R._same_product("MapBusinessOnline", "Linear"))
        self.assertFalse(R._same_product(None, "Linear"))
        self.assertTrue(R._same_product("Atlassian Jira", "Jira"))

    def test_disabled_returns_empty(self):
        with mock.patch.dict(os.environ, {"MVP_REVIEW_CONTEXT": "0"}):
            out = R.review_context("https://trello.com/", {"role": "Marketing manager"}, rivals=["Asana"])
        self.assertEqual((out["status"], out["text"]), ("disabled", ""))

    def test_no_rivals_gives_no_evidence_and_says_why(self):
        out = R.review_context("https://trello.com/", {"role": "Marketing manager"}, rivals=[])
        self.assertEqual((out["status"], out["text"]), ("no_rivals", ""))

    def test_pending_scrape_gives_no_evidence_and_says_why(self):
        with mock.patch.object(R, "cached_live_reviews", return_value=None), mock.patch.object(R, "prefetch"):
            out = R.review_context("https://trello.com/", {"role": "Marketing manager"}, rivals=["Asana"])
        self.assertEqual((out["status"], out["text"]), ("unavailable", ""))
        self.assertIn("still running", out["reason"])

    def test_evidence_comes_only_from_rival_scrapes(self):
        scraped = {"product": "Asana", "errors": [], "reviews": [
            {"source": "capterra", "product": "Asana", "role": "Marketing Manager", "rating": "5", "ease": "4", "nps": "9",
             "pros": "Boards keep campaigns on track", "cons": "Too many notifications"}]}
        with mock.patch.object(R, "cached_live_reviews", return_value=scraped), mock.patch.object(R, "prefetch"):
            out = R.review_context("https://trello.com/", {"role": "Marketing manager"}, rivals=["Asana"])
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["rivals_used"], ["Asana"])
        self.assertIn("Too many notifications", out["text"])

    def test_all_in_one_scrape_maps_fields_and_drops_other_products(self):
        items = [{"platform": "trustradius", "productName": "Asana", "rating": 4, "recommendationScore": 8, "pros": "Boards",
                  "cons": "Notifications", "text": "ok", "date": "2026-09-01",
                  "reviewer": {"jobTitle": "Marketing Manager", "companySize": "51-200 employees", "industry": "Marketing"},
                  "platformData": {"timeUsedProduct": "1-2 years", "easeOfUseRating": 4, "valueForMoneyRating": 0}},
                 {"platform": "g2", "productName": "Trello", "rating": 5}]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(R, "_APIFY_CACHE", Path(tmp)), \
                mock.patch.object(R, "apify_token", return_value="t"), mock.patch.object(R, "_apify_run", return_value=items) as run, \
                mock.patch.dict(os.environ, {"MVP_REVIEW_SCRAPER": ""}):
            out = R.live_reviews("Asana")
            self.assertEqual(run.call_args[0][0], R.ALL_IN_ONE_ACTOR)
            self.assertTrue((Path(tmp) / "aio-asana.json").is_file())
        self.assertEqual(len(out["reviews"]), 1)
        r = out["reviews"][0]
        self.assertEqual((r["source"], r["role"], r["time_used"], r["nps"]), ("trustradius", "Marketing Manager", "1-2 years", 8))
        self.assertIn("Trello", " ".join(out["errors"]))
        self.assertEqual((r["ease"], r["value"]), (4, 0))

    def test_prefetch_without_token_starts_nothing(self):
        with mock.patch.object(R, "apify_token", return_value=None), mock.patch("threading.Thread") as thread:
            R.prefetch(["Linear"])
            thread.assert_not_called()

    def test_feedback_prompt_carries_evidence_and_new_field(self):
        from mvp import study

        seen = {}

        async def fake_chat(messages, **_):
            seen["prompt"] = messages[-1]["content"]
            return '{"difficulty": "easy", "likely_frictions_from_similar_users": ["Boards get cluttered"]}'

        ctx = {"text": "## People like this person\n- overall 4.5", "category": "Project Management", "sources": ["capterra"]}
        with mock.patch.object(study, "_llm_chat", fake_chat), mock.patch.object(R, "review_context", return_value=ctx):
            out = asyncio.run(study.summarize_agent_feedback(
                url="https://trello.com/", segment="teams", persona={"name": "A", "role": "Marketing manager"},
                task={"prompt": "Create a board"}, run={"trace": [], "completed": True, "visited_urls": []}))
        self.assertIn("Evidence from live Capterra and G2 reviews of this study's competitors", seen["prompt"])
        self.assertIn("never cite it as something this session showed", seen["prompt"])
        self.assertEqual(out["likely_frictions_from_similar_users"], ["Boards get cluttered"])


if __name__ == "__main__":
    unittest.main()
