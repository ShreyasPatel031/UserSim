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
    goal_url,
    goal_visible,
    note_progress,
    pick_action,
    planned_action,
    progress_signature,
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

    def test_link_target_beats_skip_to_content(self) -> None:
        nodes = [
            {"i": 0, "role": "a", "name": "Skip to content", "href": "https://linear.app/#content", "x": 1, "y": 1},
            {"i": 1, "role": "a", "name": "Changelog", "href": "https://linear.app/changelog", "x": 2, "y": 2},
        ]
        action = pick_action("Open the changelog and see what shipped recently", nodes)
        self.assertEqual(action["href"], "https://linear.app/changelog")
        self.assertFalse(goal_visible("Find pricing", {"url": "https://linear.app/"}))
        self.assertTrue(goal_visible("Find pricing", {"url": "https://linear.app/pricing"}))
        self.assertEqual(
            goal_url("Look for pricing or how to get started", "https://linear.app/"),
            "https://linear.app/pricing",
        )
        self.assertEqual(
            goal_url("Find how to create a new issue", "https://linear.app"),
            "https://linear.app/docs/creating-issues",
        )
        self.assertEqual(goal_url("Draw a simple rectangle on the canvas", "https://excalidraw.com/"), "")
        self.assertFalse(goal_visible("Open the changelog", {"url": "https://linear.app/docs"}))
        self.assertTrue(goal_visible("Open the changelog", {"url": "https://linear.app/changelog"}))
        self.assertFalse(goal_visible("Find how to create a new issue", {"url": "https://linear.app/"}))
        self.assertFalse(
            goal_visible("Draw a simple rectangle on the canvas", {"url": "https://excalidraw.com/", "canvas": "1x1:dark=0/1;"})
        )
        self.assertTrue(
            goal_visible(
                "Draw a simple rectangle on the canvas",
                {"url": "https://excalidraw.com/?shape=rectangle", "drew": True},
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
        nodes = [
            {"i": 0, "role": "a", "name": "Get started", "href": "https://linear.app/signup", "x": 1, "y": 1},
            {"i": 1, "role": "a", "name": "Pricing", "href": "https://linear.app/pricing", "x": 2, "y": 2},
        ]
        action = planned_action("Look for pricing or how to get started", {"nodes": nodes})
        self.assertEqual(action["href"], "https://linear.app/pricing")

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

    def test_stopped_primed_session_is_replaced(self) -> None:
        """A CDP 410 prime must not be handed out. The next browser is a new create."""
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import patch

        import mvp.a11y_agent as mod

        dead = SimpleNamespace(id="dead-prime")
        also_dead = SimpleNamespace(id="dead-prime-2")
        fresh = SimpleNamespace(id="fresh-session", connect_url="wss://example/fresh")
        queue: asyncio.Queue = asyncio.Queue()
        queue.put_nowait(dead)
        queue.put_nowait(also_dead)
        discarded: list[str] = []

        class _Study:
            id = "study-1"
            budget_deadline = None

        boot = mod.A11yBoot(_Study())
        prev_queue, prev_dead = mod._PRIMED, mod._PRIMES_DEAD
        mod._PRIMED = queue
        mod._PRIMES_DEAD = False

        def _running(bb: object) -> bool:
            return False

        def _discard(bb: object) -> None:
            discarded.append(mod._session_id(bb))

        def _create(**kwargs: object) -> object:
            self.assertEqual(kwargs.get("study_id"), "study-1")
            return fresh

        try:
            with (
                patch.object(mod, "session_still_running", _running),
                patch.object(mod, "_discard_session", _discard),
                patch("capability.browserbase_client.create_session", _create),
                patch("capability.browserbase_client.study_session_owner", return_value="gates"),
            ):
                got = asyncio.run(boot._create_one(0, enqueue=False))
        finally:
            mod._PRIMED = prev_queue
            mod._PRIMES_DEAD = prev_dead
        self.assertIs(got, fresh)
        self.assertEqual(discarded, ["dead-prime", "dead-prime-2"])
        self.assertTrue(queue.empty())


if __name__ == "__main__":
    unittest.main()
