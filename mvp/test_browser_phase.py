"""Step timeout defaults and a recorded failure when history does not grow."""

from __future__ import annotations

import unittest

from mvp.browser_agent import (
    DEFAULT_LLM_TIMEOUT_S,
    DEFAULT_STEP_TIMEOUT_S,
    DOM_ELEMENT_CAP,
    _browserbase_profile,
    _cap_dom_elements,
    _cheap_dom_flags,
    _failed_trace_step,
    _last_failed_step,
    _step_is_real_action,
    _surface_swallowed_failure,
    parse_vision_action,
)


class BrowserPhaseTest(unittest.TestCase):
    def test_step_and_llm_budgets(self) -> None:
        self.assertEqual(DEFAULT_STEP_TIMEOUT_S, 60)
        self.assertEqual(DEFAULT_LLM_TIMEOUT_S, 30)

    def test_missing_history_is_a_typed_failure(self) -> None:
        step = _failed_trace_step(
            step_no=1,
            reason="Step 1 timed out after 60 seconds",
            phase="state",
        )
        self.assertEqual(step["step"], 1)
        self.assertEqual(step["action"], "step failed")
        self.assertEqual(step["failed_step"]["phase"], "state")
        self.assertIn("timed out", step["failed_step"]["reason"])
        self.assertFalse(_step_is_real_action(step))
        trace = [
            {"step": 0, "action": "Opened https://linear.app/"},
            step,
        ]
        self.assertEqual(_last_failed_step(trace)["phase"], "state")
        error, browser_error = _surface_swallowed_failure(None, None, trace)
        self.assertEqual(error, "")
        self.assertEqual(browser_error, "")
        # A later click means the run recovered. The failed row stays in the trace.
        trace.append({"step": 2, "action": "click — index=1"})
        self.assertIsNone(_last_failed_step(trace))
        self.assertTrue(_step_is_real_action(trace[-1]))

    def test_vision_coordinates_scale_from_the_small_image(self) -> None:
        got = parse_vision_action(
            {"kind": "click", "x": 400, "y": 225, "text": ""},
            width=1280,
            height=800,
        )
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got["kind"], "click")
        self.assertEqual(got["x"], 640)
        self.assertEqual(got["y"], 400)
        typed = parse_vision_action(
            '{"kind":"type","x":80,"y":40,"text":"issue"}',
            width=1280,
            height=800,
        )
        self.assertIsNotNone(typed)
        assert typed is not None
        self.assertEqual(typed["kind"], "type")
        self.assertEqual(typed["text"], "issue")
        self.assertGreater(typed["x"], 80)

    def test_dom_profile_skips_highlights_and_caps_elements(self) -> None:
        flags = _cheap_dom_flags()
        self.assertFalse(flags["dom_highlight_elements"])
        self.assertFalse(flags["highlight_elements"])
        self.assertEqual(flags["max_iframes"], 1)
        profile = _browserbase_profile("ws://127.0.0.1/devtools/browser")
        self.assertFalse(profile.dom_highlight_elements)
        self.assertEqual(profile.max_iframe_depth, 0)

        class _Node:
            def __init__(self, idx: int, y: float) -> None:
                self.selector_index = idx
                self.is_interactive = True
                self.children: list = []
                self.snapshot_node = type("S", (), {"bounds": type("B", (), {"x": 10, "y": y, "width": 20, "height": 20})()})()

        root = _Node(0, 10)
        nodes = [_Node(i, 10 if i < 3 else 5000) for i in range(1, 8)]
        root.children = nodes
        state = type("State", (), {})()
        state._root = root
        state.selector_map = {node.selector_index: node for node in [root, *nodes]}
        capped = _cap_dom_elements(state, 3)
        self.assertEqual(len(capped.selector_map), 3)
        self.assertLessEqual(DOM_ELEMENT_CAP, 40)
        kept = set(capped.selector_map)
        self.assertTrue(all(idx < 3 or idx == 0 for idx in kept))

    def test_step_hook_does_not_extract_dom_again(self) -> None:
        from pathlib import Path

        src = Path("mvp/browser_agent.py").read_text()
        hook = src.split("async def on_step_end", 1)[1].split("return on_step_start", 1)[0]
        self.assertNotIn(".get_browser_state_summary(", hook)
        self.assertNotIn("get_selector_map", hook)
        self.assertNotIn("add_highlights", hook)
        self.assertNotIn("take_screenshot", hook)
        self.assertNotIn("_page_state(", hook)


if __name__ == "__main__":
    unittest.main()
