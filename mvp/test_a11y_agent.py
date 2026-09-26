"""Shared page read: first move and the fields the strict e2e reads."""

from __future__ import annotations

import os
import unittest

from capability.gemini_config import extract_json
from mvp.a11y_agent import (
    GATE_FIELDS,
    action_label,
    apply_gate_fields,
    classify_failure,
    failure_breakdown,
    fast_action_model,
    _nodes_for_model,
    achievable_without_account,
    task_needs_account,
    format_ax,
    goal_visible,
    note_progress,
    notes_from_trace,
    offhost_excalidraw_tool,
    pick_action,
    progress_signature,
    stamp_published_step,
    study_budget_s,
    would_repeat_action,
)


class A11yAgentTest(unittest.TestCase):
    def test_tree_is_capped_text(self) -> None:
        nodes = [{"i": i, "role": "button", "name": f"Item {i}"} for i in range(200)]
        text = format_ax(nodes)
        self.assertEqual(len(text.splitlines()), 150)
        self.assertTrue(text.startswith("0 button Item 0"))

    def test_first_move_is_a_click_from_the_shared_tree(self) -> None:
        nodes = [
            {"i": 0, "role": "a", "name": "Blog", "x": 10, "y": 10},
            {"i": 1, "role": "button", "name": "Pricing", "x": 40, "y": 20},
        ]
        action = pick_action("Find pricing or the signup path", nodes)
        self.assertEqual(action["act"], "click")
        self.assertEqual(action["name"], "Pricing")
        self.assertTrue(action_label(action).startswith("click "))

    def test_issue_task_skips_decorative_new_issue(self) -> None:
        nodes = [
            {"i": 0, "role": "button", "name": "New issue", "href": "", "inert": True},
            {
                "i": 1,
                "role": "a",
                "name": "Docs",
                "href": "https://linear.app/docs/creating-issues",
            },
        ]
        action = pick_action("Find how to create a new issue", nodes)
        self.assertIn("creating-issues", action["href"])
        self.assertNotIn("new issue", action["name"].lower())
        self.assertTrue(offhost_excalidraw_tool({"act": "drag", "name": "canvas"}, "https://miro.com"))
        self.assertFalse(
            offhost_excalidraw_tool({"act": "drag", "name": "canvas"}, "https://excalidraw.com")
        )
        step = stamp_published_step(
            {"step": 1, "action": "click Docs", "url": "https://linear.app/docs/creating-issues"},
            task="Find how to create a new issue",
            read={"url": "https://linear.app/docs/creating-issues", "text": "Create issues", "title": "Creating issues"},
            screenshot_url="/api/studies/s/agents/a/screenshots/final.png",
        )
        self.assertTrue(step["final_screenshot_url"].endswith("final.png"))
        self.assertTrue(step["goal_visible"])
        self.assertIn("Create issues", step["state_sig"]["text"])

    def test_link_target_beats_skip_to_content(self) -> None:
        nodes = [
            {"i": 0, "role": "a", "name": "Skip to content", "href": "https://linear.app/#content", "x": 1, "y": 1},
            {"i": 1, "role": "a", "name": "Changelog", "href": "https://linear.app/changelog", "x": 2, "y": 2},
        ]
        action = pick_action("Open the changelog and see what shipped recently", nodes)
        self.assertEqual(action["href"], "https://linear.app/changelog")
        self.assertFalse(goal_visible("Find pricing", {"url": "https://linear.app/"}))
        self.assertTrue(goal_visible("Find pricing", {"url": "https://linear.app/pricing"}))
        self.assertFalse(goal_visible("Open the changelog", {"url": "https://linear.app/docs"}))
        self.assertTrue(goal_visible("Open the changelog", {"url": "https://linear.app/changelog"}))
        self.assertFalse(goal_visible("Find how to create a new issue", {"url": "https://linear.app/"}))
        self.assertTrue(
            goal_visible(
                "Find how to create a new issue",
                {"url": "https://linear.app/docs/creating-issues", "title": "Create issues – Linear Docs"},
            )
        )
        self.assertFalse(
            goal_visible("Draw a simple rectangle on the canvas", {"url": "https://excalidraw.com/", "canvas": "1x1:dark=0/1;", "drew": True})
        )
        self.assertFalse(
            goal_visible(
                "Draw a simple rectangle on the canvas",
                {"url": "https://excalidraw.com/", "text": "Selected shape actions Stroke width", "opened_canvas": "1440x900:dark=0/900;", "canvas": "1440x900:dark=0/900;"},
            )
        )
        self.assertTrue(
            goal_visible(
                "Draw a simple rectangle on the canvas",
                {"url": "https://excalidraw.com/", "text": "Selected shape actions", "opened_canvas": "1440x900:dark=0/900;", "canvas": "1440x900:dark=24/900;"},
            )
        )

    def test_gate_fields_are_present(self) -> None:
        sess: dict = {}
        apply_gate_fields(
            sess,
            page_open_at_ts=10.0,
            session_ready_at_ts=9.0,
            page_url="https://linear.app/",
            accessibility_tree="0 button Pricing",
            first_action_at_ts=10.2,
            phase_ms={"page_open_ms": 40, "first_action_ms": 200},
            failed_step=None,
        )
        for key in GATE_FIELDS:
            self.assertIn(key, sess)
        self.assertEqual(sess["page_opened_at_ts"], 10.0)
        self.assertEqual(sess["browser_session_ready_at_ts"], 9.0)
        self.assertEqual(sess["ax_tree"], "0 button Pricing")
        self.assertEqual(sess["phase_ms"]["first_action_ms"], 200)
        self.assertIsNone(sess["failed_step"])

    def test_action_model_is_the_lite_sibling(self) -> None:
        prev = os.environ.get("MVP_AGENT_ACTION_MODEL")
        browser = os.environ.get("MVP_BROWSER_MODEL")
        os.environ.pop("MVP_AGENT_ACTION_MODEL", None)
        os.environ["MVP_BROWSER_MODEL"] = "gemini-test-flash"
        try:
            self.assertEqual(fast_action_model(), "gemini-test-flash-lite")
            os.environ["MVP_AGENT_ACTION_MODEL"] = "gemini-explicit"
            self.assertEqual(fast_action_model(), "gemini-explicit")
        finally:
            if prev is None:
                os.environ.pop("MVP_AGENT_ACTION_MODEL", None)
            else:
                os.environ["MVP_AGENT_ACTION_MODEL"] = prev
            if browser is None:
                os.environ.pop("MVP_BROWSER_MODEL", None)
            else:
                os.environ["MVP_BROWSER_MODEL"] = browser

    def test_study_budget_is_eight_minutes(self) -> None:
        prev = os.environ.get("MVP_STUDY_BUDGET_S")
        os.environ.pop("MVP_STUDY_BUDGET_S", None)
        try:
            self.assertEqual(study_budget_s(), 480.0)
        finally:
            if prev is None:
                os.environ.pop("MVP_STUDY_BUDGET_S", None)
            else:
                os.environ["MVP_STUDY_BUDGET_S"] = prev

    def test_stops_before_a_third_identical_action(self) -> None:
        read = {"url": "https://linear.app/", "text": "Issue tracking homepage", "canvas": ""}
        trace = [
            {"step": 0, "action": "Opened https://linear.app/", "url": "https://linear.app/", "state_sig": {"text": read["text"], "canvas": ""}},
            {"step": 1, "action": "click New issue", "url": "https://linear.app/", "state_sig": {"text": read["text"], "canvas": ""}},
            {"step": 2, "action": "click New issue", "url": "https://linear.app/", "state_sig": {"text": read["text"], "canvas": ""}},
        ]
        self.assertFalse(would_repeat_action(trace[:2], "click New issue", read))
        self.assertTrue(would_repeat_action(trace, "click New issue", read))
        self.assertFalse(
            goal_visible(
                "Find how to create a new issue",
                {"url": "https://linear.app/changelog/new-issue-ui", "title": "Changelog"},
            )
        )
        kept = _nodes_for_model(
            [
                {"i": 0, "role": "button", "name": "New issue", "inert": True},
                {"i": 1, "role": "a", "name": "Pricing", "href": "https://linear.app/pricing"},
                {"i": 2, "role": "a", "name": "Docs", "href": "https://linear.app/docs"},
                {"i": 3, "role": "a", "name": "Log in", "href": "https://linear.app/login"},
            ],
            {"new issue"},
        )
        self.assertEqual([node["name"] for node in kept], ["Pricing", "Docs"])
        easy, friction = notes_from_trace(
            [
                {"step": 0, "action": "Opened https://linear.app/", "url": "https://linear.app/"},
                {"step": 1, "action": "click New issue", "url": "https://linear.app/", "changed": False},
                {
                    "step": 2,
                    "action": "click Pricing",
                    "url": "https://linear.app/pricing",
                    "changed": True,
                    "decision": {"easy": "Pricing was in the header."},
                },
            ]
        )
        self.assertTrue(any("Pricing" in line and "pricing" in line for line in easy))
        self.assertTrue(any("changed nothing" in line for line in friction))
        self.assertFalse(any("free plan is listed" in line for line in easy))

    def test_canvas_flicker_does_not_excuse_a_repeated_click(self) -> None:
        read = {"url": "https://miro.com/index/", "text": "Miro homepage", "canvas": "dark=100"}
        trace = [
            {"step": 0, "action": "Opened https://miro.com/", "url": "https://miro.com/", "state_sig": {"text": "Miro", "canvas": "dark=2888"}},
            {"step": 1, "action": "click Export image", "url": "https://miro.com/index/", "state_sig": {"text": "Miro", "canvas": "dark=1444"}},
            {"step": 2, "action": "click Export image", "url": "https://miro.com/index/", "state_sig": {"text": "Miro", "canvas": "dark=2018"}},
        ]
        self.assertFalse(would_repeat_action(trace[:2], "click Export image", read))
        self.assertTrue(would_repeat_action(trace, "click Export image", read))
        self.assertFalse(
            goal_visible(
                "Draw a simple box",
                {"url": "https://excalidraw.com/", "text": "Selected shape actions", "opened_canvas": "1440x900:dark=0/900;", "canvas": "1440x900:dark=0/900;"},
            )
        )
        self.assertTrue(
            goal_visible(
                "Draw a simple box",
                {"url": "https://excalidraw.com/", "opened_canvas": "1440x900:dark=0/900;", "canvas": "1440x900:dark=18/900;"},
            )
        )

    def test_stuck_after_three_identical_signatures(self) -> None:
        sig = progress_signature(
            url="https://linear.app/",
            screenshot_hash="abc",
            text="Issue tracking",
            canvas="canvas:0",
        )
        streak, reason = note_progress(None, sig, 0)
        self.assertEqual(streak, 0)
        self.assertEqual(reason, "")
        streak, reason = note_progress(sig, sig, streak)
        self.assertEqual(streak, 1)
        streak, reason = note_progress(sig, sig, streak)
        self.assertEqual(streak, 2)
        streak, reason = note_progress(sig, sig, streak)
        self.assertEqual(streak, 3)
        self.assertIn("stuck:", reason)
        self.assertIn("screenshot hash", reason)
        moved = progress_signature(
            url="https://linear.app/pricing",
            screenshot_hash="def",
            text="Pricing",
            canvas="canvas:0",
        )
        streak, reason = note_progress(sig, moved, 2)
        self.assertEqual(streak, 0)
        self.assertEqual(reason, "")

    def test_failure_buckets(self) -> None:
        self.assertEqual(classify_failure(stop_reason="stuck: no progress for 3 consecutive steps"), "stuck")
        self.assertEqual(classify_failure(stop_reason="browser dead: target closed"), "our infrastructure")
        self.assertEqual(classify_failure(stop_reason="study budget"), "our infrastructure")
        self.assertEqual(
            classify_failure(error="gemini model timed out"),
            "model timeout",
        )
        self.assertEqual(classify_failure(stop_reason="done", goal_reached=False), "product")
        self.assertEqual(classify_failure(stop_reason="done", goal_reached=True), "")
        table = failure_breakdown(
            [
                {"site_key": "product", "agent_id": "a", "stop_reason": "stuck: no progress for 3 consecutive steps"},
                {"site_key": "product", "agent_id": "b", "stop_reason": "done", "goal_reached": False},
                {"site_key": "competitor", "agent_id": "c", "stop_reason": "browser dead: closed"},
            ]
        )
        self.assertEqual(table["counts"]["stuck"], 1)
        self.assertEqual(table["counts"]["product"], 1)
        self.assertEqual(table["counts"]["our infrastructure"], 1)

    def test_extract_json_keeps_the_first_object(self) -> None:
        self.assertEqual(extract_json('{"act":"click","i":1}\n{"act":"done"}'), {"act": "click", "i": 1})
        self.assertEqual(extract_json('note {"act":"drag"} trailing'), {"act": "drag"})

    def test_account_tasks_are_kept(self) -> None:
        self.assertEqual(
            achievable_without_account("https://linear.app/", "Create a new issue in your workspace"),
            "Create a new issue in your workspace",
        )
        self.assertTrue(task_needs_account("Create an issue"))
        self.assertTrue(task_needs_account("Make a board"))
        self.assertFalse(task_needs_account("Find how to create a new issue"))
        self.assertFalse(
            goal_visible(
                "Create an issue",
                {"url": "https://linear.app/docs/creating-issues", "title": "Create issues – Linear Docs"},
            )
        )
        self.assertTrue(
            goal_visible(
                "Create an issue",
                {"url": "https://linear.app/team/issue/new", "text": "Issue title\nDescription"},
            )
        )
        self.assertTrue(
            goal_visible(
                "Create an issue",
                {
                    "url": "https://linear.app/usersim/team/active",
                    "text": "Inbox",
                    "nodes": [
                        {"name": "Issue title"},
                        {"name": "Add description..."},
                    ],
                },
            )
        )


if __name__ == "__main__":
    unittest.main()
