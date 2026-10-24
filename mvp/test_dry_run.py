"""POST /api/studies with dry_run: planner only, no study, browsers, Browserbase or signup."""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi.testclient import TestClient

PLAN = {
    "dry_run": True,
    "url": "https://linear.app/",
    "ok": True,
    "personas": [{"name": "Priya Okafor"}],
    "tasks": [{"prompt": "Create an issue", "favors": "product"}],
    "rivals": [{"url": "https://asana.com/", "live": True, "reason": "ok", "name": "Asana"}],
    "validation": [{"name": "plan", "ok": True, "detail": "compare plan"}],
    "usage": {"gemini_calls": 2, "input_tokens": 4000, "output_tokens": 900, "est_cost_usd": 0.00345},
}


class DryRunEndpointTests(unittest.TestCase):
    def setUp(self):
        from mvp.server import app

        self.client = TestClient(app, raise_server_exceptions=False)

    async def _landing(self, url):
        return url

    def test_dry_run_returns_the_plan_and_starts_nothing(self):
        from mvp.study import STUDIES

        before = set(STUDIES)
        calls = []

        async def fake_dry_run(url, **kw):
            calls.append(url)
            return dict(PLAN, url=url)

        with mock.patch("mvp.server._landing_url", self._landing), \
                mock.patch("mvp.plan_check.dry_run_plan", fake_dry_run), \
                mock.patch("mvp.study.create_study") as create, \
                mock.patch("mvp.study.run_study") as run, \
                mock.patch("mvp.browser_slots.prefetch_count") as prefetch, \
                mock.patch("mvp.preopen.start_preopen") as preopen:
            resp = self.client.post("/api/studies", json={"url": "linear.app", "dry_run": True})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["dry_run"])
        self.assertEqual(body["url"], "https://linear.app")
        self.assertEqual(body["rivals"][0]["name"], "Asana")
        self.assertIn("validation", body)
        self.assertNotIn("study_id", body)
        self.assertEqual(calls, ["https://linear.app"])
        for m in (create, run, prefetch, preopen):
            m.assert_not_called()
        self.assertEqual(set(STUDIES), before)

    def test_dry_run_defaults_to_false(self):
        from mvp.server import StudyRequest

        self.assertFalse(StudyRequest(url="linear.app").dry_run)

    def test_without_dry_run_the_study_path_runs(self):
        async def boom(url, **kw):
            raise AssertionError("dry run must not run without dry_run")

        with mock.patch("mvp.server._landing_url", self._landing), \
                mock.patch("mvp.plan_check.dry_run_plan", boom), \
                mock.patch("mvp.study.create_study", side_effect=RuntimeError("study path reached")):
            resp = self.client.post("/api/studies", json={"url": "linear.app"})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("study path reached", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
