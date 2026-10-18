"""Agent mode: rating level from own reviews shrunk to rivals, no silent fallbacks, MCP tool wiring (offline)."""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest import mock

from mvp import agent_mode as A
from mvp import review_context as RC


def _rev(product, rating, **kw):
    return {"source": "capterra", "product": product, "rating": rating, **kw}


OWN = {"product": "Basecamp", "errors": [], "reviews": [_rev("Basecamp", 5, ease=5, nps=10, role="Project Manager",
                                                             pros="Simple to-dos", cons="Weak reporting")] * 20}
RIVAL = {"product": "Asana", "errors": [], "reviews": [_rev("Asana", 4, ease=4, nps=8, role="Marketing Manager",
                                                            pros="Boards", cons="Too many notifications")] * 30}


def _run(**kw):
    async def fake_llm(prompt):
        fake_llm.prompt = prompt
        return {"pros": ["Simple to-dos"], "cons": ["Weak reporting"], "overall_experience": "Fine.", "likely_frictions": []}
    out = asyncio.run(A.predict_experience(product="Basecamp", url="https://basecamp.com/", persona={"role": "Project manager"},
                                           competitors=["Asana"], wait_s=0, llm=fake_llm, **kw))
    return out, getattr(fake_llm, "prompt", "")


class AgentModeTest(unittest.TestCase):
    def test_rating_is_own_mean_shrunk_to_rivals(self):
        r = A.rating_estimates(OWN["reviews"], RIVAL["reviews"])
        self.assertAlmostEqual(r["overall_rating"]["estimate"], round((20 * 5 + A.K * 4) / (20 + A.K), 2))
        self.assertEqual(r["overall_rating"]["basis"], "own reviews shrunk to rivals")
        self.assertAlmostEqual(r["recommendation_score"]["estimate"], round((20 * 10 + A.K * 8) / (20 + A.K), 2))

    def test_persona_offsets_lower_a_trial_user(self):
        r = A.rating_estimates(OWN["reviews"], RIVAL["reviews"])
        A.personalize(r, {"role": "Project manager", "company_size": "30 people", "time_used": "trial"})
        rec = r["recommendation_score"]
        self.assertIn("time_used=I used a free trial", rec["persona_offsets"])
        self.assertIn("size_fine=11-50 employees", rec["persona_offsets"])
        self.assertLess(rec["persona_offsets"]["time_used=I used a free trial"], 0)
        self.assertLess(rec["for_this_persona"], rec["estimate"])

    def test_rivals_only_when_product_has_no_reviews(self):
        r = A.rating_estimates([], RIVAL["reviews"])
        self.assertEqual((r["overall_rating"]["estimate"], r["overall_rating"]["basis"]), (4.0, "rivals only (no own reviews)"))

    def test_g2_ease_is_rescaled_and_zero_means_unrated(self):
        self.assertEqual(A._values([{"ease_1_7": 7}, {"ease": 0, "ease_1_7": 1}], "ease_of_use_rating"), [5.0, 1.0])
        self.assertEqual(A._values([{"nps": 0}], "recommendation_score"), [0.0])

    def test_ok_result_with_words_and_evidence(self):
        got = {"Basecamp": OWN, "Asana": RIVAL}
        with mock.patch.object(RC, "apify_token", return_value="t"), mock.patch.object(RC, "prefetch"), \
                mock.patch.object(RC, "cached_live_reviews", side_effect=lambda n: got.get(n)):
            out, prompt = _run()
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["evidence"]["own_reviews"], 20)
        self.assertEqual(out["cons"], ["Weak reporting"])
        self.assertIn("This product's own earlier reviews", prompt)
        self.assertIn("Time using Basecamp", prompt)
        self.assertIn("People like this person", prompt)
        self.assertIn("Too many notifications", prompt)

    def test_rivals_discovered_from_url_when_none_given(self):
        got = {"Basecamp": OWN, "Asana": RIVAL}

        async def discover(url):
            return ["Asana"]

        async def fake_llm(prompt):
            return {}
        with mock.patch.object(RC, "apify_token", return_value="t"), mock.patch.object(RC, "prefetch"), \
                mock.patch.object(RC, "cached_live_reviews", side_effect=lambda n: got.get(n)):
            out = asyncio.run(A.predict_experience(product="Basecamp", url="https://basecamp.com/", persona={"role": "PM"},
                                                   wait_s=0, llm=fake_llm, discover=discover))
        self.assertEqual(out["evidence"]["rivals"], ["Asana"])
        self.assertEqual(out["evidence"]["rivals_source"], "discovered by the study planner")
        self.assertEqual(out["ratings"]["overall_rating"]["n_rivals"], 30)

    def test_pending_while_product_scrape_runs(self):
        with mock.patch.object(RC, "apify_token", return_value="t"), mock.patch.object(RC, "prefetch"), \
                mock.patch.object(RC, "cached_live_reviews", return_value=None):
            out, _ = _run()
        self.assertEqual(out["status"], "pending")
        self.assertIn("Basecamp", out["pending"])

    def test_no_token_says_so_and_scrapes_nothing(self):
        with mock.patch.object(RC, "apify_token", return_value=None), mock.patch.object(RC, "prefetch") as pf:
            out, _ = _run()
        self.assertEqual(out["status"], "no_data")
        self.assertIn("APIFY_TOKEN", out["reason"])
        pf.assert_not_called()

    def test_no_reviews_anywhere_is_no_data(self):
        empty = {"reviews": [], "errors": []}
        with mock.patch.object(RC, "apify_token", return_value="t"), mock.patch.object(RC, "prefetch"), \
                mock.patch.object(RC, "cached_live_reviews", return_value=empty):
            out, _ = _run()
        self.assertEqual(out["status"], "no_data")

    def test_mcp_tool_is_listed_and_returns_json(self):
        from mvp.sim_mcp import server as srv

        names = [t.name for t in asyncio.run(srv.mcp.list_tools())]
        self.assertIn("usersim_predict_experience", names)
        with mock.patch.dict(os.environ, {"MVP_MCP_LIMITS_URL": "off"}), \
                mock.patch.object(srv, "_owner", return_value="tokenowner"), \
                mock.patch.object(RC, "apify_token", return_value=None):
            raw = asyncio.run(srv.usersim_predict_experience(None, product="Basecamp", persona={"role": "PM"}, product_url="",
                                                             task="", competitors=None))
        self.assertEqual(json.loads(raw)["mode"], "agent")


if __name__ == "__main__":
    unittest.main()
