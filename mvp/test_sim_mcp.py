"""Offline tests for the MCP simulated-user path (no Browserbase, no judge calls)."""

from __future__ import annotations

import io
import random
import unittest

from mvp.e2e2_gates import is_click_type_scroll
from mvp.sim_mcp import sessions as S
from mvp.sim_mcp.report import build_report, proof_checks, report_markdown


def _png(noisy: bool = True) -> bytes:
    from PIL import Image

    im = Image.new("RGB", (320, 200), (255, 255, 255))
    if noisy:
        rnd = random.Random(1)
        px = im.load()
        for x in range(320):
            for y in range(200):
                px[x, y] = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


class UrlGuardTests(unittest.TestCase):
    def test_public_url_normalized(self):
        self.assertEqual(S.normalize_public_url("example.com/app"), "https://example.com/app")

    def test_localhost_and_private_rejected(self):
        for bad in ("http://localhost:3000", "http://127.0.0.1/", "http://10.0.0.5/", "http://myapp.local", ""):
            with self.assertRaises(S.SessionError, msg=bad):
                S.normalize_public_url(bad)

    def test_same_site(self):
        product = "https://app.linear.app/team"
        self.assertTrue(S.same_site("https://linear.app/pricing", product))
        self.assertTrue(S.same_site("https://accounts.google.com/o/oauth2", product))
        self.assertFalse(S.same_site("https://evil.com/", product))
        self.assertTrue(S.same_site("https://foo.vercel.app/x", "https://foo.vercel.app/"))
        self.assertFalse(S.same_site("https://bar.vercel.app/x", "https://foo.vercel.app/"))


class ActionTests(unittest.TestCase):
    product = "https://example.com/"

    def test_validates_coordinates(self):
        S.validate_action({"type": "click", "x": 10, "y": 10}, self.product)
        for bad in ({"type": "click"}, {"type": "click", "x": 5000, "y": 1}, {"type": "fly"}, {"type": "type", "text": ""}):
            with self.assertRaises(S.SessionError, msg=bad):
                S.validate_action(dict(bad), self.product)

    def test_navigate_is_same_site_only(self):
        S.validate_action({"type": "navigate", "url": "https://example.com/b"}, self.product)
        with self.assertRaises(S.SessionError):
            S.validate_action({"type": "navigate", "url": "https://other.org/"}, self.product)

    def test_wait_is_clamped_and_scroll_defaults_to_center(self):
        self.assertEqual(S.validate_action({"type": "wait", "ms": 99999}, self.product)["ms"], 5000)
        a = S.validate_action({"type": "scroll", "dy": 300}, self.product)
        self.assertEqual((a["x"], a["y"]), (S.VIEWPORT["width"] // 2, S.VIEWPORT["height"] // 2))

    def test_trace_text_counts_as_real_action_for_the_gates(self):
        for action in (
            {"type": "click", "x": 1, "y": 2},
            {"type": "double_click", "x": 1, "y": 2},
            {"type": "type", "text": "hi"},
            {"type": "scroll", "dy": 3, "x": 1, "y": 1},
        ):
            self.assertTrue(is_click_type_scroll(S.describe_action(action)), action)
        for action in ({"type": "navigate", "url": "https://x.com"}, {"type": "wait", "ms": 5}, {"type": "back"}):
            self.assertFalse(is_click_type_scroll(S.describe_action(action)), action)


class ProofAndReportTests(unittest.TestCase):
    def _study(self, tmp, *, steps, live=True, png=None):
        sid = "s1"
        shots = tmp / sid / S.AGENT_ID / "screenshots"
        shots.mkdir(parents=True)
        trace = []
        for i, (action, url, text) in enumerate(steps):
            (shots / f"step_{i}.png").write_bytes(png if png is not None else _png())
            trace.append(
                {
                    "step": i,
                    "action": action,
                    "thought": "where is the price? confusing" if i == 1 else "",
                    "url": url,
                    "screenshot_url": f"/api/studies/{sid}/agents/{S.AGENT_ID}/screenshots/step_{i}.png",
                    "state_sig": {"text": text},
                }
            )
        row = {
            "agent_id": S.AGENT_ID,
            "site_url": "https://shop.example.com/",
            "page_url": "https://shop.example.com/",
            "task_prompt": "buy a book",
            "persona_bio": "teacher",
            "trace": trace,
            "last_action": steps[-1][0],
            "live_view_url": "https://www.browserbase.com/devtools-fullscreen/x" if live else "",
        }
        study = {"id": sid, "url": row["site_url"], "driver": S.DRIVER, "test_mode": False, "status": "complete"}
        return study, row

    def _patch_runs(self, tmp):
        import mvp.sim_mcp.report as R

        old = R.MVP_RUNS_DIR
        R.MVP_RUNS_DIR = tmp
        self.addCleanup(setattr, R, "MVP_RUNS_DIR", old)

    def test_real_run_passes(self):
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp())
        self._patch_runs(tmp)
        study, row = self._study(
            tmp,
            steps=[
                ("Opened https://shop.example.com/", "https://shop.example.com/", "home"),
                ("click — (10, 20)", "https://shop.example.com/books/1", "book page"),
            ],
        )
        proof = proof_checks(study, row, "ok")
        self.assertTrue(proof["pass"], proof)

    def test_failures_are_named(self):
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp())
        self._patch_runs(tmp)
        study, row = self._study(
            tmp,
            steps=[("Opened https://shop.example.com/", "https://shop.example.com/", "home")],
            live=False,
            png=_png(noisy=False),
        )
        proof = proof_checks(study, row, "error: judge failed")
        failed = {c["name"] for c in proof["checks"] if not c["pass"]}
        self.assertFalse(proof["pass"])
        self.assertEqual(
            failed,
            {"real_action", "screenshots_real", "beyond_first_screen", "live_view_offered", "judge_ran"},
        )

    def test_report_separates_judge_from_driver_claim(self):
        study = {
            "id": "s1",
            "url": "https://shop.example.com/",
            "status": "complete",
            "summary": {"headline": "did not reach", "proof": {"pass": True, "checks": []}, "judge_status": "ok"},
            "agent_results": [
                {
                    "persona_bio": "teacher",
                    "task_prompt": "buy",
                    "driver_outcome": "completed",
                    "feedback": "easy",
                    "page_verdict": {"goal_reached": False, "reason": "still on home"},
                    "trace": [
                        {"step": 0, "action": "Opened", "url": "u", "screenshot_url": "/a.png"},
                        {"step": 1, "action": "click — (1, 1)", "url": "u", "thought": "I can't find checkout", "screenshot_url": "/b.png"},
                    ],
                }
            ],
            "engine_version": "abc",
        }
        rep = build_report(study)
        self.assertFalse(rep["judge"]["goal_reached"])
        self.assertEqual(rep["driver_claim"]["outcome"], "completed")
        self.assertEqual([f["step"] for f in rep["friction"]], [1])
        md = report_markdown(rep)
        self.assertIn("goal NOT reached", md)
        self.assertIn("Engine: abc", md)


if __name__ == "__main__":
    unittest.main()
