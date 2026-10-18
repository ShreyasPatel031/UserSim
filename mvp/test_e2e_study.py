"""Full-study (e2e) shape enforcement — docs/E2E_TEST.md."""

from __future__ import annotations

import unittest
from unittest import mock

from mvp.e2e_study import (
    E2EStudyRejected,
    ensure_full_study_inputs,
    reject_disallowed_flags,
    validate_supplied_counts,
)
from mvp.sim_mcp import sessions as S


class E2EStudyTests(unittest.TestCase):
    def test_reject_smoke_flags(self):
        with self.assertRaises(E2EStudyRejected) as ctx:
            reject_disallowed_flags(test_mode=True)
        self.assertIn("E2E_TEST.md", str(ctx.exception))
        with self.assertRaises(E2EStudyRejected):
            reject_disallowed_flags(skip_competitors=True)

    def test_reject_wrong_competitor_count(self):
        with self.assertRaises(E2EStudyRejected):
            validate_supplied_counts(["https://a.com"], None, None)
        with self.assertRaises(E2EStudyRejected):
            validate_supplied_counts(["https://a.com", "https://b.com", "https://c.com"], None, None)

    def test_reject_wrong_persona_or_task_count(self):
        with self.assertRaises(E2EStudyRejected):
            validate_supplied_counts(None, [{"bio": "x"}], None)
        with self.assertRaises(E2EStudyRejected):
            validate_supplied_counts(None, None, ["only one"])

    def test_api_rejects_test_mode(self):
        from fastapi.testclient import TestClient

        from mvp.server import app

        client = TestClient(app)
        res = client.post(
            "/api/studies",
            json={"url": "https://example.com", "test_mode": True},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("E2E_TEST.md", res.json().get("detail", ""))

    def test_create_matrix_rejects_partial_matrix(self):
        with self.assertRaises(S.SessionError) as ctx:
            S.create_matrix_study(
                product_url="https://notion.com",
                competitors=["https://coda.io"],
                personas=[{"bio": "x"}],
                tasks=[{"prompt": "y"}],
            )
        self.assertIn("E2E_TEST.md", str(ctx.exception))

    def test_create_matrix_accepts_full_shape(self):
        people = [{"name": f"P{i}", "bio": f"bio {i}"} for i in range(6)]
        jobs = [{"prompt": f"Task {i}"} for i in range(6)]
        study = S.create_matrix_study(
            product_url="notion.com",
            competitors=["https://coda.io", "clickup.com"],
            personas=people,
            tasks=jobs,
        )
        self.assertEqual(len(study.tasks), 108)

    def test_ensure_fills_from_compare_plan(self):
        plan = {
            "mode": "compare",
            "competitors": ["https://coda.io", "https://clickup.com"],
            "personas": [{"name": f"P{i}", "bio": f"b{i}"} for i in range(6)],
            "task_specs": [{"prompt": f"T{i}"} for i in range(6)],
        }

        async def _run():
            with mock.patch("mvp.e2e_study.compare_plan_from_url", return_value=plan):
                return await ensure_full_study_inputs("https://notion.com", [], [], [])

        import asyncio

        comps, pers, jobs = asyncio.run(_run())
        self.assertEqual(len(comps), 2)
        self.assertEqual(len(pers), 6)
        self.assertEqual(len(jobs), 6)


if __name__ == "__main__":
    unittest.main()
