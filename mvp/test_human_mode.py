"""Human mode: bounded combination with agent mode, first-session notes dropped, no silent fallbacks, MCP wiring (offline)."""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest import mock

from mvp import human_mode as H
from mvp import review_context as RC

BASE = {"mode": "agent", "status": "ok", "product": "Basecamp", "ratings": {"overall_rating": {"estimate": 4.4}},
        "pros": ["Easy to use", "Good communication", "Flat pricing"], "cons": ["Basic reporting", "Few integrations", "No time tracking"],
        "overall_experience": "Fine.", "how_to_read": "Agent."}
OBS = [{"kind": "product_friction", "what": "Calendar does not show to-do due dates."},
       {"kind": "product_friction", "what": "Free plan allows one project."},
       {"kind": "product_benefit", "what": "Adding to-dos inline is fast."},
       {"kind": "agent_failure", "what": "I misclicked."}]


def _llm(themes, edit):
    async def llm(prompt, system, temperature=0.0):
        llm.prompts.append(prompt)
        return {"themes": themes} if "theme" in prompt.split("\n")[0] else edit
    llm.prompts = []
    return llm


async def _agent_ok(**kw):
    return dict(BASE)


def _combine(llm, agent=_agent_ok, obs=OBS):
    return asyncio.run(H.combine(product="Basecamp", url="https://basecamp.com/", persona={"role": "PM"}, observations=obs,
                                 llm=llm, agent=agent))


class HumanModeTest(unittest.TestCase):
    def test_first_session_notes_dropped_and_one_edit_per_side(self):
        edit = {"pros": ["Easy to use", "Good communication", "Quick to add and assign tasks"],
                "cons": ["Basic reporting", "Calendar does not pull in task due dates", "No time tracking"], "changed": ["a", "b"]}
        llm = _llm(["ui_ease_navigation", "free_plan_or_tier_limits", "core_feature_depth_or_missing"], edit)
        out = _combine(llm)
        self.assertEqual(out["mode"], "human")
        self.assertEqual(out["ratings"], BASE["ratings"])  # ratings are agent mode's
        self.assertEqual(out["pros"], edit["pros"])
        self.assertEqual(out["cons"], edit["cons"])
        self.assertEqual(len(out["observations_used"]), 2)
        self.assertIn("Free plan allows one project", out["observations_dropped_first_session"][0])
        self.assertNotIn("misclicked", llm.prompts[-1])  # agent failures never reach the model
        self.assertEqual(out["agent_mode"]["cons"], BASE["cons"])

    def test_own_reviews_rewrite_words_with_observations_and_keep_ratings(self):
        calls = []

        async def agent(**kw):
            calls.append(kw)
            base = {**BASE, "evidence": {"own_reviews": 60}}
            if kw.get("llm"):
                words = await kw["llm"]("WORDS PROMPT")
                return {**base, "pros": words["pros"], "cons": words["cons"], "overall_experience": words["overall_experience"],
                        "ratings": {"overall_rating": {"estimate": 1.0}}}
            return base

        async def words_llm(prompt):
            words_llm.prompt = prompt
            return {"pros": ["Fast to-do entry"], "cons": ["Calendar ignores to-do dates"], "overall_experience": "Good."}
        out = asyncio.run(H.combine(product="Basecamp", url="https://basecamp.com/", persona={"role": "PM"}, observations=OBS,
                                    agent=agent, words_llm=words_llm))
        self.assertEqual(out["cons"], ["Calendar ignores to-do dates"])
        self.assertEqual(out["ratings"], BASE["ratings"])  # the first (agent-mode) ratings, not the rewrite's
        self.assertEqual(out["agent_mode"]["cons"], BASE["cons"])
        self.assertIn("WORDS PROMPT", words_llm.prompt)
        self.assertIn("Calendar does not show to-do due dates", words_llm.prompt)
        self.assertNotIn("misclicked", words_llm.prompt)
        self.assertEqual(len(calls), 2)

    def test_revision_changing_too_much_is_rejected(self):
        edit = {"pros": ["a", "b", "c"], "cons": ["d", "e", "f"]}
        out = _combine(_llm(["ui_ease_navigation", "ui_ease_navigation", "ui_ease_navigation"], edit))
        self.assertEqual(out["pros"], BASE["pros"])
        self.assertEqual(out["cons"], BASE["cons"])

    def test_only_first_session_notes_leaves_agent_mode_unchanged(self):
        llm = _llm(["setup_configuration", "free_plan_or_tier_limits", "onboarding_learning_curve"], {})
        out = _combine(llm)
        self.assertEqual(out["pros"], BASE["pros"])
        self.assertIn("no usable product observations", out["human_note"])
        self.assertEqual(len(llm.prompts), 1)  # no edit call

    def test_agent_mode_not_ready_is_passed_through(self):
        async def pending(**kw):
            return {"mode": "agent", "status": "pending", "reason": "scraping"}
        out = _combine(_llm([], {}), agent=pending)
        self.assertEqual((out["mode"], out["status"]), ("human", "pending"))
        self.assertIn("scraping", out["reason"])

    def test_plan_needs_rivals_and_builds_task_from_their_complaints(self):
        got = {"Asana": {"reviews": [{"product": "Asana", "cons": "Too many notifications and the reporting is very basic for managers"}],
                         "errors": []}}

        async def llm(prompt, system, temperature=0.0):
            if "planner named" in prompt:
                return {"reviews_are_of_named_product": True, "direct_competitor": "yes", "why": "same job"}
            llm.prompt = prompt
            return {"task": "Do the work.", "core_job": "manage projects", "features": ["views", "reports"]}
        with mock.patch.object(RC, "prefetch"), mock.patch.object(RC, "cached_live_reviews", side_effect=lambda n: got.get(n)):
            out = asyncio.run(H.plan(product="Basecamp", url="https://basecamp.com/", persona="a PM", competitors=["Asana"],
                                     wait_s=0, llm=llm))
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["start_session"]["task"], "Do the work.")
        self.assertIn("reporting is very basic", llm.prompt)

        async def not_rival(prompt, system, temperature=0.0):
            return {"reviews_are_of_named_product": True, "direct_competitor": "no", "why": "different job"}
        with mock.patch.object(RC, "prefetch"), mock.patch.object(RC, "cached_live_reviews", side_effect=lambda n: got.get(n)):
            out = asyncio.run(H.plan(product="Basecamp", url="https://basecamp.com/", persona="a PM", competitors=["Asana"],
                                     wait_s=0, llm=not_rival))
        self.assertEqual(out["status"], "no_data")
        self.assertFalse(out["rivals_checked"][0]["used"])

        async def none(url):
            return []
        out = asyncio.run(H.plan(product="Basecamp", url="https://basecamp.com/", persona="", llm=llm, discover=none))
        self.assertEqual(out["status"], "no_data")

    def test_mcp_tools_are_listed_and_return_json(self):
        from mvp.sim_mcp import server as srv

        names = [t.name for t in asyncio.run(srv.mcp.list_tools())]
        self.assertIn("usersim_plan_human_run", names)
        self.assertIn("usersim_combine_human_run", names)
        with mock.patch.dict(os.environ, {"MVP_MCP_LIMITS_URL": "off"}), \
                mock.patch.object(srv, "_owner", return_value="tokenowner"), \
                mock.patch.object(RC, "apify_token", return_value=None):
            raw = asyncio.run(srv.usersim_combine_human_run(None, product="Basecamp", persona={"role": "PM"}, observations=OBS,
                                                            product_url="", task="", competitors=["Asana"]))
        out = json.loads(raw)
        self.assertEqual((out["mode"], out["status"]), ("human", "no_data"))


if __name__ == "__main__":
    unittest.main()
