"""Step timeout defaults and a recorded failure when history does not grow."""

from __future__ import annotations

import unittest

from mvp.browser_agent import (
    DEFAULT_LLM_TIMEOUT_S,
    DEFAULT_STEP_TIMEOUT_S,
    _failed_trace_step,
    _last_failed_step,
    _step_is_real_action,
    _surface_swallowed_failure,
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


if __name__ == "__main__":
    unittest.main()
