"""Competitor URLs passed with a study stay the plan's rivals (Statable vs Plausible and Fathom, 2026-09-30).

The planner was never told the request's rivals: it invented Matomo, and the server kept the passed URLs for
visits but took names, jobs and buyers tagged for Matomo. Two buyers and two jobs favored a site no agent
visited and none favored Fathom.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from collections import Counter
from unittest import mock

from mvp import fast_plan

URL = "https://statable.com"
PLAUSIBLE = "https://plausible.io/"
FATHOM = "https://usefathom.com/"
MATOMO = "https://matomo.org/"


def _persona(name: str, favors: str) -> dict:
    return {"name": name, "role": "Founder at a SaaS startup", "bio": "Wants simple traffic numbers.", "favors": favors, "why": "fits"}


def _task(text: str, favors: str) -> dict:
    return {"task": text, "favors": favors, "why": "fits"}


# What the model answered on production: Plausible and Matomo, never Fathom.
INVENTED_PLAN = {
    "product": "Statable",
    "segment": "Founders choosing privacy-friendly web analytics",
    "competitors": [{"url": PLAUSIBLE, "name": "Plausible"}, {"url": MATOMO, "name": "Matomo"}],
    "backup_competitor": {"url": "https://simpleanalytics.com/", "name": "Simple Analytics"},
    "personas": [
        _persona("Ana Ruiz", "product"),
        _persona("Ben Okoro", "product"),
        _persona("Cara Lund", PLAUSIBLE),
        _persona("Dev Shah", PLAUSIBLE),
        _persona("Eva Brandt", MATOMO),
        _persona("Finn Moss", MATOMO),
    ],
    "tasks": [
        _task("Create a traffic dashboard", "product"),
        _task("Share a public stats page", "product"),
        _task("Find the top referrer last week", PLAUSIBLE),
        _task("Set up a goal for signups", PLAUSIBLE),
        _task("Export raw visit logs", MATOMO),
        _task("Build a custom heatmap report", MATOMO),
        _task("Compare bounce rate by country", MATOMO),
    ],
}


class FakeModel:
    """Answers each planner prompt by kind; records the prompts it saw."""

    def __init__(self, plan: dict, persona_topup: dict | None = None, task_topup: dict | None = None) -> None:
        self.plan = plan
        self.persona_topup = persona_topup or {"personas": []}
        self.task_topup = task_topup or {"tasks": []}
        self.prompts: list[str] = []

    async def __call__(self, messages, **_kw) -> str:
        prompt = messages[0]["content"]
        self.prompts.append(prompt)
        if prompt.startswith("Add target customers"):
            return json.dumps(self.persona_topup)
        if prompt.startswith("Add jobs"):
            return json.dumps(self.task_topup)
        return json.dumps(self.plan)


async def _read(_url: str) -> dict:
    return {"title": "Statable - simple web analytics", "text": "Privacy-first website analytics.", "links": []}


async def _land(url: str) -> str:
    return url


def _plan(model: FakeModel, competitors: list[str] | None) -> dict | None:
    env = {"MVP_STUDY_MODE": "compare", "MVP_COMPARE_PLAN_SPLIT": "0", "MVP_PLAN_FRAMING": "read"}
    with mock.patch.dict(os.environ, env), \
            mock.patch("capability.gemini_config.gemini_chat", model), \
            mock.patch.object(fast_plan, "_page_read", _read), \
            mock.patch("mvp.server._landing_url", _land):
        return asyncio.run(fast_plan.plan_from_url(URL, competitors=competitors))


def _hosts(urls) -> set[str]:
    return {fast_plan._host_of(u) for u in urls}


class PinnedRivals(unittest.TestCase):
    def assert_shape(self, plan: dict, rivals: list[str]) -> None:
        self.assertEqual(plan["mode"], "compare")
        self.assertEqual(plan["competitors"], rivals)
        self.assertEqual(set(plan["competitor_names"]), set(rivals))
        sites = ["product"] + rivals
        for rows in (plan["personas"], plan["task_specs"]):
            self.assertEqual(len(rows), 6)
            self.assertEqual(Counter(r["favors"] for r in rows), Counter({s: 2 for s in sites}))
        self.assertNotIn("matomo.org", json.dumps(plan))

    def test_statable_keeps_fathom_and_never_favors_matomo(self) -> None:
        model = FakeModel(
            INVENTED_PLAN,
            persona_topup={"personas": [_persona("Gus Lee", FATHOM), _persona("Hana Ito", "Fathom"), _persona("Ivo Park", FATHOM)]},
            task_topup={"tasks": [_task("Check live visitors now", FATHOM), _task("Filter traffic by campaign", FATHOM)]},
        )
        plan = _plan(model, [PLAUSIBLE, FATHOM])
        self.assertIsNotNone(plan)
        self.assert_shape(plan, [PLAUSIBLE, FATHOM])
        self.assertIn(FATHOM, model.prompts[0])
        fathom_people = [p["name"] for p in plan["personas"] if p["favors"] == FATHOM]
        self.assertEqual(sorted(fathom_people), ["Gus Lee", "Ivo Park"])
        fathom_jobs = [t["prompt"] for t in plan["task_specs"] if t["favors"] == FATHOM]
        self.assertEqual(sorted(fathom_jobs), ["Check live visitors now", "Filter traffic by campaign"])

    def test_shape_holds_when_the_model_keeps_inventing_matomo(self) -> None:
        stubborn = FakeModel(
            INVENTED_PLAN,
            persona_topup={"personas": [_persona("Jo Matt", MATOMO)]},
            task_topup={"tasks": [_task("Audit self-hosted install", MATOMO)]},
        )
        plan = _plan(stubborn, ["plausible.io", "https://usefathom.com/"])
        self.assertIsNotNone(plan)
        self.assert_shape(plan, ["plausible.io", "https://usefathom.com/"])

    def test_no_competitors_still_invents_rivals(self) -> None:
        model = FakeModel(INVENTED_PLAN)
        plan = _plan(model, None)
        self.assertIsNotNone(plan)
        self.assertEqual(_hosts(plan["competitors"]), {"plausible.io", "matomo.org"})
        self.assertEqual(Counter(p["favors"] for p in plan["personas"])[MATOMO], 2)
        self.assertFalse(any("fixed by the person running the study" in p for p in model.prompts))

    def test_pinned_rivals_skip_the_product_and_repeats(self) -> None:
        got = fast_plan.pinned_rivals([" https://statable.com/pricing", PLAUSIBLE, "https://www.plausible.io/x", FATHOM, MATOMO], "statable.com")
        self.assertEqual(got, [PLAUSIBLE, FATHOM])

    def test_plan_with_a_substitute_rival_does_not_keep_the_pins(self) -> None:
        self.assertTrue(fast_plan.plan_keeps_rivals({"competitors": ["https://www.plausible.io/", FATHOM]}, [PLAUSIBLE, FATHOM]))
        self.assertFalse(fast_plan.plan_keeps_rivals({"competitors": [PLAUSIBLE, MATOMO]}, [PLAUSIBLE, FATHOM]))


class StartStudyKeepsPinnedRivals(unittest.TestCase):
    """POST /api/studies for Statable with Plausible and Fathom: the study's plan is tagged for those two."""

    def test_statable_request(self) -> None:
        from fastapi.testclient import TestClient

        from mvp import server
        from mvp.study import STUDIES

        model = FakeModel(
            INVENTED_PLAN,
            persona_topup={"personas": [_persona("Gus Lee", FATHOM), _persona("Ivo Park", FATHOM)]},
            task_topup={"tasks": [_task("Check live visitors now", FATHOM), _task("Filter traffic by campaign", FATHOM)]},
        )
        planned = asyncio.Event()
        seen: dict = {}

        async def run_study(study_id: str, **_kw):
            seen["id"] = study_id
            planned.set()

        async def landing(url: str) -> str:
            return url.rstrip("/")

        env = {
            "MVP_STUDY_MODE": "compare", "MVP_COMPARE_PLAN_SPLIT": "0", "MVP_PLAN_FRAMING": "read",
            "MVP_ATTACH_STREAM": "0", "MVP_FAST_PLAN": "1", "MVP_EARLY_START": "0",
        }
        with mock.patch.dict(os.environ, env), \
                mock.patch("capability.gemini_config.gemini_chat", model), \
                mock.patch.object(fast_plan, "_page_read", _read), \
                mock.patch.object(server, "_landing_url", landing), \
                mock.patch("mvp.study.run_study", run_study), \
                mock.patch("mvp.preopen.start_preopen", lambda *a, **k: None), \
                mock.patch("mvp.browser_slots.prefetch_count", lambda *a, **k: None), \
                mock.patch("mvp.early_start.enabled", lambda: False), \
                TestClient(server.app) as client:
            res = client.post("/api/studies", json={"url": URL, "competitors": [PLAUSIBLE, FATHOM]})
            self.assertEqual(res.status_code, 200, res.text)
            client.portal.call(asyncio.wait_for, planned.wait(), 10)
        study = STUDIES[seen["id"]]
        self.assertEqual(study.competitors, [PLAUSIBLE, FATHOM])
        self.assertEqual(set(study.competitor_names), {PLAUSIBLE, FATHOM})
        sites = ["product", PLAUSIBLE, FATHOM]
        for rows in (study.plan_personas, study.task_specs):
            self.assertEqual(Counter(r["favors"] for r in rows), Counter({s: 2 for s in sites}))
        self.assertNotIn("matomo", json.dumps([study.competitor_names, study.plan_personas, study.task_specs]))


class BalanceFavors(unittest.TestCase):
    def test_off_list_and_surplus_rows_fill_the_short_site(self) -> None:
        rows = [{"favors": f, "favors_why": "x"} for f in ["product", "product", "product", "a", "a", MATOMO]]
        out = fast_plan.balance_favors(rows, ["product", "a", "b"], 2)
        self.assertEqual(Counter(r["favors"] for r in out), Counter({"product": 2, "a": 2, "b": 2}))
        self.assertEqual([r["favors"] for r in out[:2]], ["product", "product"])


if __name__ == "__main__":
    unittest.main()
