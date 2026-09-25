"""Claims in the study report must cite a real screenshot step."""

from __future__ import annotations

import unittest

from mvp.report_insights import (
    build_report_insights,
    changed_page_state,
    left_start,
    task_succeeded,
    work_metrics,
)


def _run(
    agent_id: str,
    *,
    site_key: str = "product",
    steps: int = 1,
    difficulty: str = "easy",
    convert: str = "maybe",
    final: str = "https://linear.app/",
    easy: list[str] | None = None,
    friction: list[str] | None = None,
    quote: str = "",
) -> dict:
    trace = []
    for i in range(steps):
        trace.append(
            {
                "step": i,
                "action": f"Opened step {i}",
                "url": final,
                "screenshot_url": f"/api/studies/s/agents/{agent_id}/screenshots/bbox_{i}.png",
                "outcome": "friction" if friction and i == steps - 1 else "neutral",
            }
        )
    return {
        "agent_id": agent_id,
        "persona_name": "Pat",
        "task_title": "Skim the homepage",
        "site_key": site_key,
        "site_label": "Product" if site_key == "product" else site_key,
        "site_url": final,
        "num_steps": steps,
        "difficulty": difficulty,
        "would_convert": convert,
        "final_url": final,
        "what_was_easy": easy or [],
        "friction_points": friction or [],
        "quote": quote,
        "trace": trace,
    }


class WorkMetricTests(unittest.TestCase):
    def test_homepage_only_is_not_task_success(self) -> None:
        run = _run("a", steps=1, final="https://docs.python.org/3/")
        self.assertFalse(task_succeeded(run, "https://docs.python.org/3/"))
        self.assertFalse(left_start(run, "https://docs.python.org/3/"))

    def test_leaving_the_start_url_after_a_click_is_success(self) -> None:
        run = _run("a", steps=2, final="https://docs.python.org/3/tutorial/")
        run["site_url"] = "https://docs.python.org/3/"
        run["trace"][0]["url"] = "https://docs.python.org/3/"
        run["trace"][1]["action"] = "click — index=4"
        run["trace"][1]["url"] = "https://docs.python.org/3/tutorial/"
        self.assertTrue(left_start(run, "https://docs.python.org/3/"))
        self.assertTrue(task_succeeded(run, "https://docs.python.org/3/"))
        metrics = work_metrics([run], "https://docs.python.org/3/")
        self.assertEqual(metrics["left_start_pct"], 100)
        self.assertEqual(metrics["task_success_rate"], 100)
        self.assertEqual(metrics["median_steps"], 2)

    def test_done_after_a_click_on_the_same_url_counts(self) -> None:
        run = _run("a", steps=2, final="https://excalidraw.com/")
        run["site_url"] = "https://excalidraw.com/"
        run["trace"][1]["action"] = "done — text=Opened the menu and found Export image"
        run["trace"][1]["url"] = "https://excalidraw.com/"
        run["trace"][0]["action"] = "click — index=25"
        self.assertFalse(left_start(run, "https://excalidraw.com/"))
        self.assertTrue(task_succeeded(run, "https://excalidraw.com/"))

    def test_canvas_drag_changes_page_state_without_a_url_change(self) -> None:
        run = _run("a", steps=2, final="https://excalidraw.com/")
        run["site_url"] = "https://excalidraw.com/"
        blank = "900x600:" + ",".join(["10"] * 64)
        drawn = "900x600:" + ",".join(["10"] * 20 + ["200"] * 44)
        run["trace"][0]["url"] = "https://excalidraw.com/"
        run["trace"][0]["state_sig"] = {"text": "excalidraw canvas", "canvas": blank}
        run["trace"][1]["action"] = "drag — start_x=120 start_y=180 end_x=400 end_y=320"
        run["trace"][1]["url"] = "https://excalidraw.com/"
        run["trace"][1]["state_sig"] = {"text": "excalidraw canvas", "canvas": drawn}
        run["trace"][1]["step_latency_s"] = 4.2
        self.assertFalse(left_start(run, "https://excalidraw.com/"))
        self.assertTrue(changed_page_state(run, "https://excalidraw.com/"))
        self.assertTrue(task_succeeded(run, "https://excalidraw.com/"))
        metrics = work_metrics([run], "https://excalidraw.com/")
        self.assertEqual(metrics["changed_page_pct"], 100)
        self.assertEqual(metrics["left_start_pct"], 0)
        self.assertEqual(metrics["step_latency_p50"], 4.2)

    def test_one_canvas_sample_is_not_a_page_change(self) -> None:
        run = _run("a", steps=2, final="https://excalidraw.com/")
        run["site_url"] = "https://excalidraw.com/"
        base = "900x600:" + ",".join(["10"] * 64)
        flicker = "900x600:" + ",".join(["10"] * 63 + ["11"])
        run["trace"][0]["state_sig"] = {"text": "excalidraw", "canvas": base}
        run["trace"][1]["action"] = "click — index=29"
        run["trace"][1]["state_sig"] = {"text": "excalidraw", "canvas": flicker}
        self.assertFalse(changed_page_state(run, "https://excalidraw.com/"))
        self.assertFalse(task_succeeded(run, "https://excalidraw.com/"))


class InsightTests(unittest.TestCase):
    def test_generic_load_notes_are_not_strengths(self) -> None:
        study = {
            "url": "https://linear.app/",
            "status": "complete",
            "agent_results": [
                _run(
                    "t1__p1__product",
                    easy=["The page loaded without any obvious issues."],
                    quote="The homepage loaded quickly.",
                )
            ],
            "activity_log": [],
        }
        insights = build_report_insights(study)
        self.assertEqual(insights["strengths"], [])
        self.assertTrue(insights["evidence_thin"])
        self.assertIn("thin", insights["headline"].lower())
        self.assertTrue(insights["weaknesses"])
        ev = insights["weaknesses"][0]["evidence"][0]
        self.assertEqual(ev["agent_id"], "t1__p1__product")
        self.assertIn("bbox_0.png", ev["screenshot_url"])
        self.assertEqual(ev["final_url"], "https://linear.app/")

    def test_drawing_canvas_is_a_strength_and_a_bare_load_is_not(self) -> None:
        study = {
            "url": "https://excalidraw.com/",
            "agent_results": [
                _run(
                    "t2__p2__product",
                    final="https://excalidraw.com/",
                    easy=["The site loaded quickly and presented a clear drawing canvas immediately."],
                ),
                _run(
                    "t1__p1__product",
                    final="https://excalidraw.com/",
                    easy=["The page loaded without issues"],
                ),
            ],
            "activity_log": [],
        }
        insights = build_report_insights(study)
        self.assertEqual(len(insights["strengths"]), 1)
        self.assertIn("drawing canvas", insights["strengths"][0]["claim"])
        self.assertEqual(insights["strengths"][0]["evidence"][0]["agent_id"], "t2__p2__product")

    def test_concrete_quote_cites_the_step_shot(self) -> None:
        study = {
            "url": "https://linear.app/",
            "agent_results": [
                _run(
                    "t1__p1__product",
                    quote="The design is clean and modern, which is a good first impression.",
                )
            ],
            "activity_log": [],
        }
        insights = build_report_insights(study)
        self.assertEqual(len(insights["strengths"]), 1)
        ev = insights["strengths"][0]["evidence"][0]
        self.assertEqual(ev["step"], 0)
        self.assertTrue(ev["screenshot_url"].endswith("bbox_0.png"))

    def test_success_tie_orders_by_steps_then_time_then_friction(self) -> None:
        fast = _run("a", site_key="product", steps=1, final="https://linear.app/")
        slow = _run(
            "b",
            site_key="competitor_1",
            steps=4,
            final="https://asana.com/",
            friction=["Pricing table is hard to compare."],
        )
        study = {
            "url": "https://linear.app/",
            "agent_results": [fast, slow],
            "activity_log": [
                {"kind": "agent_start", "agent_id": "a", "at": "2026-09-25T20:00:00+00:00"},
                {"kind": "agent_done", "agent_id": "a", "at": "2026-09-25T20:00:10+00:00"},
                {"kind": "agent_start", "agent_id": "b", "at": "2026-09-25T20:00:00+00:00"},
                {"kind": "agent_done", "agent_id": "b", "at": "2026-09-25T20:01:00+00:00"},
            ],
        }
        # n>=2 required per site for a tie. Add a twin for each.
        study["agent_results"].append(
            _run("a2", site_key="product", steps=1, final="https://linear.app/")
        )
        study["agent_results"].append(
            _run("b2", site_key="competitor_1", steps=4, final="https://asana.com/")
        )
        insights = build_report_insights(study)
        self.assertIsNotNone(insights["tie_note"])
        self.assertIn("fewer steps", insights["tie_note"])
        self.assertEqual(insights["comparisons"][0]["site_key"], "product")
        self.assertLess(
            insights["comparisons"][0]["median_steps"],
            insights["comparisons"][1]["median_steps"],
        )


if __name__ == "__main__":
    unittest.main()
