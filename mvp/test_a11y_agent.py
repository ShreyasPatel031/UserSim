"""Shared page read: first move and the fields the strict e2e reads."""

from __future__ import annotations

import os
import unittest

from mvp.a11y_agent import (
    GATE_FIELDS,
    action_label,
    apply_gate_fields,
    classify_failure,
    failure_breakdown,
    fast_action_model,
    format_ax,
    goal_visible,
    keep_step_stamps,
    note_progress,
    pick_action,
    progress_signature,
    promote_live_session_fields,
    study_budget_s,
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

    def test_live_session_gets_ax_and_page_open_from_the_trace(self) -> None:
        sess = {
            "agent_id": "t1__p1__product",
            "site_url": "https://linear.app/",
            "trace": [
                {
                    "step": 0,
                    "url": "https://linear.app/",
                    "ax_tree": "0 button New issue",
                    "page_open_at_ts": 1_000.0,
                    "session_ready_at_ts": 999.0,
                }
            ],
        }
        promote_live_session_fields(sess)
        self.assertEqual(sess["ax_tree"], "0 button New issue")
        self.assertEqual(sess["accessibility_tree"], "0 button New issue")
        self.assertEqual(sess["page_open_at_ts"], 1_000.0)
        self.assertEqual(sess["page_opened_at_ts"], 1_000.0)
        self.assertEqual(sess["created_at_ts"], 1_000.0)
        self.assertEqual(sess["page_url"], "https://linear.app/")
        self.assertEqual(sess["session_ready_at_ts"], 999.0)

    def test_promote_does_not_wipe_existing_stamps(self) -> None:
        sess = {
            "site_url": "https://linear.app/",
            "page_open_at_ts": 50.0,
            "ax_tree": "0 button Pricing",
            "created_at_ts": 49.0,
            "page_url": "https://linear.app/",
            "trace": [{"step": 1, "action": "click New issue", "url": "https://linear.app/team"}],
        }
        promote_live_session_fields(sess, {"step": 1, "action": "click New issue"})
        self.assertEqual(sess["page_open_at_ts"], 50.0)
        self.assertEqual(sess["ax_tree"], "0 button Pricing")
        self.assertEqual(sess["created_at_ts"], 49.0)
        self.assertEqual(sess["page_url"], "https://linear.app/")

    def test_replaced_step_keeps_page_open_and_ax(self) -> None:
        previous = {
            "step": 0,
            "page_open_at_ts": 10.0,
            "ax_tree": "0 button Save",
            "url": "https://trello.com/",
            "phase_ms": {"page_open": 40},
        }
        incoming = {"step": 0, "action": "Opened", "url": "https://trello.com/"}
        keep_step_stamps(previous, incoming)
        self.assertEqual(incoming["page_open_at_ts"], 10.0)
        self.assertEqual(incoming["ax_tree"], "0 button Save")
        self.assertEqual(incoming["phase_ms"]["page_open"], 40)

    def test_promote_uses_the_assigned_host(self) -> None:
        sess = {
            "site_url": "https://trello.com/",
            "page_url": "https://linear.app/",
            "created_at_ts": 5.0,
            "trace": [
                {
                    "step": 0,
                    "url": "https://linear.app/",
                    "ax_tree": "0 a Login",
                    "page_open_at_ts": 5.0,
                },
                {"step": 1, "url": "https://trello.com/", "ax_tree": "0 button Sign up"},
            ],
        }
        promote_live_session_fields(sess)
        self.assertEqual(sess["page_url"], "https://trello.com/")
        self.assertEqual(sess["opened_url"], "https://trello.com/")
        self.assertEqual(sess["ax_tree"], "0 a Login")
        self.assertEqual(sess["created_at_ts"], 5.0)

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


if __name__ == "__main__":
    unittest.main()
