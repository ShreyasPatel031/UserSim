"""Oct 11: verified signups are judged against the signup bar with 2-of-3 votes (Raygun, StatusCake onboarding)."""
from __future__ import annotations

import asyncio
import io
import unittest
from unittest import mock


def _png() -> bytes:
    from PIL import Image

    im = Image.new("RGB", (320, 200), "white")
    for x in range(0, 320, 7):  # some structure so the frame is not "unrendered"
        for y in range(0, 200, 5):
            im.putpixel((x, y), ((x * 3) % 255, (y * 5) % 255, 90))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def _row(verified: bool) -> dict:
    row = {"signup_email": "usersim.signups+t1@gmail.com", "task_prompt": "Create an account ... reach the signed-in dashboard.",
           "site_url": "https://raygun.com/", "final_url": "https://app.raygun.com/onboarding/setup-raygun/",
           "trace": [], "agent_id": "t1__p1__product"}
    if verified:
        row.update(signup_mail=[{"from": "no-reply@raygun.com", "subject": "Verify your email"}], signup_code_used=True)
    return row


class VoteTests(unittest.TestCase):
    def _run(self, row, answers, tmp):
        from mvp.sim_mcp import report as R

        calls = []

        def fake(png, *, task, **kw):
            calls.append(task)
            return answers[len(calls) - 1]

        d = tmp / "sid" / "t1__p1__product" / "screenshots"
        d.mkdir(parents=True)
        (d / "final.png").write_bytes(_png())
        with mock.patch.object(R, "MVP_RUNS_DIR", tmp), mock.patch("mvp.e2e2_gates.judge_goal_screenshot", fake), \
                mock.patch.object(R, "frame_unrendered", lambda png: False), \
                mock.patch("mvp.e2e2_gates.judge_signed_in", lambda *a, **k: {"signed_in": False}):
            verdict, status = asyncio.run(R.judge_run("sid", row))
        return verdict, status, calls

    def test_two_of_three_pass_uses_signup_bar(self):
        import pathlib
        import tempfile

        from mvp.sim_mcp.report import SIGNUP_BAR_TASK

        yes = {"goal_reached": True, "signed_in_app_page": True, "reason": "onboarding inside app"}
        no = {"goal_reached": False, "signed_in_app_page": True, "reason": "not the dashboard"}
        with tempfile.TemporaryDirectory() as t:
            v, status, calls = self._run(_row(True), [no, yes, yes], pathlib.Path(t))
        self.assertEqual(status, "ok")
        self.assertTrue(v["goal_reached"])
        self.assertEqual(v["votes_yes"], 2)
        self.assertEqual(len(v["votes"]), 3)
        self.assertTrue(all(c == SIGNUP_BAR_TASK for c in calls))

    def test_majority_settles_early(self):
        import pathlib
        import tempfile

        no = {"goal_reached": False, "signed_in_app_page": False, "reason": "login form"}
        with tempfile.TemporaryDirectory() as t:
            v, _, calls = self._run(_row(True), [no, no, no], pathlib.Path(t))
        self.assertFalse(v["goal_reached"])
        self.assertEqual(len(calls), 2)

    def test_unverified_signup_single_vote_and_never_passes(self):
        import pathlib
        import tempfile

        yes = {"goal_reached": True, "signed_in_app_page": True, "reason": "x"}
        with tempfile.TemporaryDirectory() as t:
            v, _, calls = self._run(_row(False), [yes], pathlib.Path(t))
        self.assertEqual(len(calls), 1)
        self.assertNotIn("votes", v)
        self.assertFalse(v["goal_reached"])  # hard rule: a signup never passes unverified
