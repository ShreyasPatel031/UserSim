"""The judge also looks at earlier frames when the final one misses the goal (studies 7da0e18c, 32f5d74d, Nov 18)."""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mvp.sim_mcp import report as R


def _png(color=(250, 250, 250)) -> bytes:
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (1280, 800), color)
    d = ImageDraw.Draw(im)
    for i in range(0, 800, 20):  # enough detail that frame_unrendered() calls it a page
        d.text((20, i), f"line {i} " * 20, fill=(10, 10, 10))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class EarlierFramesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(R, "MVP_RUNS_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)
        self.sid, self.aid = "s1", "t1__p1__product"
        shots = self.tmp / self.sid / self.aid / "screenshots"
        shots.mkdir(parents=True)
        png = _png()
        kinds = ["open", "click", "scroll", "click", "type", "scroll", "scroll"]
        self.trace = []
        for i, kind in enumerate(kinds):
            (shots / f"step_{i}.png").write_bytes(png)
            self.trace.append({"step": i, "action_kind": kind, "url": "https://x.test/",
                               "screenshot_url": f"/api/studies/s1/agents/{self.aid}/screenshots/step_{i}.png"})
        (shots / "final.png").write_bytes(png)
        self.row = {"agent_id": self.aid, "site_url": "https://x.test/", "task_prompt": "Approve the changes you would ship",
                    "trace": self.trace, "final_url": "https://x.test/"}

    def test_frames_after_actions_first_most_recent_first_final_excluded(self):
        steps = [s["step"] for s in R.earlier_frame_steps(self.sid, self.row, 5)]
        self.assertEqual(steps, [4, 3, 1, 5, 2])

    def _judge(self, reached_steps):
        def fake(png, *, task, start_url, final_url="", dom="", evidence="", dom_limit=1500):
            step = fake.order.pop(0) if fake.order else None
            return {"goal_reached": step in reached_steps, "reason": f"frame {step}"}
        return fake

    def test_goal_seen_mid_run_counts_and_keeps_both_reasons(self):
        calls = []

        def fake(png, *, task, start_url, final_url="", dom="", evidence="", dom_limit=1500):
            calls.append(final_url)
            # the final frame (dom passed) says no; earlier frames: only one says yes
            if dom:
                return {"goal_reached": False, "reason": "final frame: no approvals visible"}
            return {"goal_reached": len(calls) == 3, "reason": "two Approved items visible"}

        self.row["final_dom"] = "report text"
        with mock.patch("mvp.e2e2_gates.judge_goal_screenshot", fake):
            verdict, status = asyncio.run(R.judge_run(self.sid, self.row))
        self.assertEqual(status, "ok")
        self.assertTrue(verdict["goal_reached"])
        self.assertIn(verdict["reached_at_step"], {4, 3, 1, 5, 2})
        self.assertTrue(verdict["reason"].startswith("Reached at step"))
        self.assertIn("no approvals", verdict["final_frame_reason"])

    def test_no_frame_shows_it_stays_not_reached(self):
        fake = lambda png, **k: {"goal_reached": False, "reason": "stuck on captcha"}  # noqa: E731
        self.row["final_dom"] = "x"
        with mock.patch("mvp.e2e2_gates.judge_goal_screenshot", fake):
            verdict, _ = asyncio.run(R.judge_run(self.sid, self.row))
        self.assertFalse(verdict["goal_reached"])
        self.assertNotIn("reached_at_step", verdict)

    def test_switch_off(self):
        calls = []

        def fake(png, **k):
            calls.append(1)
            return {"goal_reached": False, "reason": "no"}

        with mock.patch.dict(os.environ, {"MVP_JUDGE_EARLIER_FRAMES": "0"}), \
                mock.patch("mvp.e2e2_gates.judge_goal_screenshot", fake):
            verdict, _ = asyncio.run(R.judge_run(self.sid, self.row))
        self.assertEqual(len(calls), 1)  # final frame only
        self.assertFalse(verdict["goal_reached"])

    def test_final_frame_reached_means_no_extra_calls(self):
        calls = []

        def fake(png, **k):
            calls.append(1)
            return {"goal_reached": True, "reason": "done"}

        with mock.patch("mvp.e2e2_gates.judge_goal_screenshot", fake):
            verdict, _ = asyncio.run(R.judge_run(self.sid, self.row))
        self.assertEqual(len(calls), 1)
        self.assertTrue(verdict["goal_reached"])


if __name__ == "__main__":
    unittest.main()
