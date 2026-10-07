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
        self.assertFalse(S.same_site("https://accounts.google.com/o/oauth2", product))
        self.assertTrue(S.blocked_signin("https://accounts.google.com/o/oauth2"))
        self.assertTrue(S.same_site("https://login.microsoftonline.com/x", product))
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


class MatrixStudyTests(unittest.TestCase):
    """A study built over MCP has the same shape the website report reads."""

    def _study(self):
        return S.create_matrix_study(
            product_url="notion.com",
            competitors=["https://coda.io", "clickup.com"],
            personas=[
                {"name": "Maya", "bio": "Freelance writer", "favors": "notion"},
                {"name": "Raj", "bio": "Ops analyst", "favors": "https://coda.io"},
            ],
            tasks=[{"prompt": "Find the free plan limits"}, {"prompt": "Price a team of 8", "favors": "clickup.com"}],
        )

    def test_every_persona_task_site_is_a_queued_cell(self):
        from mvp.study import STUDIES

        study = self._study()
        self.assertIs(STUDIES[study.id], study)
        self.assertEqual(len(study.tasks), 2 * 2 * 3)
        self.assertEqual(set(study.live_sessions), {t["id"] for t in study.tasks})
        self.assertIn("t1__p1__product", study.live_sessions)
        self.assertIn("t2__p2__competitor_2", study.live_sessions)
        self.assertTrue(all(r["status"] == "queued" for r in study.live_sessions.values()))
        self.assertEqual(study.study_mode, "compare")
        self.assertEqual(study.backend, "mcp")
        self.assertEqual(study.competitor_names, {"https://coda.io": "Coda", "https://clickup.com": "Clickup"})

    def test_favors_resolve_to_a_site_url(self):
        study = self._study()
        self.assertEqual([p["favors"] for p in study.personas], ["https://notion.com", "https://coda.io"])
        self.assertEqual([t["favors"] for t in study.task_specs], ["", "https://clickup.com"])

    def test_competitor_cells_run_on_the_competitor(self):
        study = self._study()
        cell = study.live_sessions["t1__p1__competitor_1"]
        self.assertEqual(cell["site_url"], "https://coda.io")
        self.assertEqual(cell["site_label"], "Coda")

    def test_cell_starts_once_and_rejects_unknown_ids(self):
        study = self._study()
        sim = S._cell_session(study.id, "t1__p2__competitor_1", "")
        self.assertEqual(sim.agent_id, "t1__p2__competitor_1")
        self.assertTrue(sim.matrix)
        self.assertEqual(sim.product_url, "https://coda.io")
        self.assertIn("Raj", sim.persona)
        with self.assertRaises(S.SessionError):
            S._cell_session(study.id, "t1__p2__competitor_1", "")  # already starting
        with self.assertRaises(S.SessionError):
            S._cell_session(study.id, "t9__p9__product", "")
        with self.assertRaises(S.SessionError):
            S._cell_session("nope", "t1__p1__product", "")

    def test_bad_inputs(self):
        with self.assertRaises(S.SessionError):
            S.create_matrix_study(product_url="https://notion.com", competitors=["notion.com/pricing"], personas=[{"bio": "x"}], tasks=["y"])
        with self.assertRaises(S.SessionError):
            S.create_matrix_study(product_url="https://notion.com", competitors=[], personas=[], tasks=["y"])
        many = [{"bio": f"p{i}"} for i in range(8)]
        with self.assertRaises(S.SessionError):
            S.create_matrix_study(product_url="https://a.com", competitors=["https://b.com", "https://c.com"], personas=many, tasks=["1", "2", "3"])

    def test_study_report_lists_every_cell(self):
        from mvp.sim_mcp.report import build_study_report, is_matrix, study_report_markdown
        from mvp.study import study_to_dict

        study = self._study()
        data = study_to_dict(study)
        self.assertTrue(is_matrix(data))
        rep = build_study_report(data)
        self.assertEqual(len(rep["cells"]), 12)
        self.assertIn("/report?study=", study_report_markdown(rep))


class SignupToolsTests(unittest.TestCase):
    def test_only_signup_inbox_allowed(self):
        from mvp.signup_tools import inbox_allowed

        self.assertTrue(inbox_allowed("usersim.signups+abc@gmail.com"))
        self.assertFalse(inbox_allowed("someone.else+abc@gmail.com"))

    def test_drag_and_hold_validate(self):
        a = S.validate_action({"type": "drag", "x": 1, "y": 2, "to_x": 50, "to_y": 2}, "https://ex.com")
        self.assertEqual(a["to_x"], 50)
        h = S.validate_action({"type": "press_and_hold", "x": 1, "y": 2}, "https://ex.com")
        self.assertEqual(h["ms"], 4000)


class BearerTests(unittest.TestCase):
    def test_bearer_guard(self):
        import asyncio

        from mvp.sim_mcp.server import _require_bearer

        hits = []

        async def inner(scope, receive, send):
            hits.append(1)

        sent = []

        async def send(msg):
            sent.append(msg)

        async def receive():
            return {"type": "http.request"}

        app = _require_bearer(inner, "s3cret")
        asyncio.run(app({"type": "http", "headers": []}, receive, send))
        self.assertEqual(sent[0]["status"], 401)
        asyncio.run(app({"type": "http", "headers": [(b"authorization", b"Bearer s3cret")]}, receive, send))
        self.assertEqual(hits, [1])


class TypeEmailGuardTests(unittest.TestCase):
    def test_made_up_email_refused_signup_inbox_ok(self):
        import os
        from mvp.sim_mcp.sessions import SessionError, validate_action

        os.environ.setdefault("MVP_SIGNUP_ALLOWED_LOCAL", "usersimsignups")
        with self.assertRaises(SessionError):
            validate_action({"type": "type", "text": "ben.podcaster@example.com"}, "https://example.org")
        validate_action({"type": "type", "text": "usersim.signups+x1@gmail.com"}, "https://example.org")
        validate_action({"type": "type", "text": "hello world"}, "https://example.org")
