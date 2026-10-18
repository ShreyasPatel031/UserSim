"""Competitor review evidence: product matching, opt-out, background-only live scrapes, feedback prompt wiring."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest import mock

from mvp import review_context as R


class ReviewContextTest(unittest.TestCase):
    def test_same_product_rejects_other_search_hits(self):
        self.assertTrue(R._same_product("Trello", "trello"))
        self.assertTrue(R._same_product("Zoho CRM", "Zoho"))
        self.assertFalse(R._same_product("MapBusinessOnline", "Linear"))
        self.assertFalse(R._same_product(None, "Linear"))

    def test_disabled_returns_empty(self):
        with mock.patch.dict(os.environ, {"MVP_REVIEW_CONTEXT": "0"}):
            self.assertEqual(R.review_context("https://trello.com/", {"role": "Marketing manager"})["text"], "")

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
        self.assertIn("Evidence from real Capterra and G2 reviews", seen["prompt"])
        self.assertIn("never cite it as something this session showed", seen["prompt"])
        self.assertEqual(out["likely_frictions_from_similar_users"], ["Boards get cluttered"])


if __name__ == "__main__":
    unittest.main()
