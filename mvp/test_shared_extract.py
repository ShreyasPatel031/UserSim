"""Shared page cache: one read per site, first actions before any agent browser."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace


class SharedExtractTests(unittest.TestCase):
    def test_shared_js_is_one_extract(self) -> None:
        from mvp.shared_extract import _SHARED_PAGE_JS

        self.assertIn("getBoundingClientRect", _SHARED_PAGE_JS)
        self.assertNotIn("DOMSnapshot", _SHARED_PAGE_JS)
        self.assertNotIn("Accessibility.getFullAXTree", _SHARED_PAGE_JS)
        self.assertLessEqual(_SHARED_PAGE_JS.count("querySelectorAll"), 3)

    def test_first_action_runs_before_any_per_agent_read(self) -> None:
        src = Path("mvp/shared_extract.py").read_text()
        body = src.split("async def run_shared_agent", 1)[1]
        self.assertLess(body.index("_act_on_page"), body.index("page.evaluate"))
        self.assertNotIn("get_browser_state_summary", body)

    def test_done_reply_becomes_a_click(self) -> None:
        from mvp.shared_extract import coerce_first_action

        elements = [
            {"i": 1, "tag": "a", "text": "Pricing", "x": 10, "y": 20, "w": 40, "h": 16},
            {"i": 2, "tag": "button", "text": "Login", "x": 80, "y": 20, "w": 40, "h": 16},
        ]
        got = coerce_first_action({"kind": "done", "index": 0}, elements, "Find pricing")
        self.assertEqual(got["kind"], "click")
        self.assertEqual(got["index"], 1)
        self.assertEqual(got["x"], 30)
        self.assertEqual(got["y"], 28)

    def test_publish_records_the_three_clocks_from_one_cache(self) -> None:
        from mvp.shared_extract import SharedExtractBoot, note_submitted

        study = SimpleNamespace(
            id="study-1",
            url="https://linear.app",
            personas=[{"id": "p1", "name": "Ava", "bio": "PM"}],
            tasks=[
                {
                    "id": "t1__p1__product",
                    "persona_id": "p1",
                    "site_key": "product",
                    "site_url": "https://linear.app",
                    "site_label": "Product",
                    "title": "Find pricing",
                    "prompt": "Find pricing",
                }
            ],
            live_sessions={},
            activity_log=[],
            updated_at="",
            summary=None,
            agent_results=[],
        )
        note_submitted(study)
        boot = SharedExtractBoot(study, None)
        page = {
            "final_url": "https://linear.app/",
            "url": "https://linear.app/",
            "text": "Linear pricing",
            "canvas": "",
            "nodes": [{"i": 0, "role": "link", "name": "Pricing"}],
            "elements": [
                {"i": 1, "tag": "a", "text": "Pricing", "x": 10, "y": 20, "w": 40, "h": 16}
            ],
            "shot_path": "",
            "capture_ms": 1200,
        }
        decision = {"kind": "click", "index": 1, "x": 30, "y": 28, "text": ""}
        boot._publish("product", page, {"t1__p1__product": decision})
        sess = study.live_sessions["t1__p1__product"]
        self.assertEqual(sess["created_at_ts"], sess["page_open_at_ts"])
        self.assertEqual(sess["page_open_at_ts"], sess["first_action_at_ts"])
        self.assertIn("Pricing", sess["accessibility_tree"])
        self.assertTrue(str(sess["trace"][1]["action"]).startswith("click"))
        self.assertEqual(study.ux_metrics["time_to_first_value_agent"], "t1__p1__product")
        self.assertIsNotNone(study.ux_metrics["time_to_first_value_s"])
        self.assertIn("t1__p1__product", study.ux_metrics["per_agent_time_to_first_action_s"])
        self.assertEqual(len(boot.snapshots), 0)


if __name__ == "__main__":
    unittest.main()
