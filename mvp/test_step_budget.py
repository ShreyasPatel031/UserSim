"""Step budget: captcha wait and DOM capture must not cancel the model call."""

from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace

from mvp.browser_agent import (
    MVP_CAPTCHA_WAIT_S,
    MVP_HOLD_S,
    MVP_LLM_TIMEOUT_S,
    MVP_STATE_TIMEOUT_S,
    MVP_STEP_TIMEOUT_S,
    action_step_budget_s,
    bounded_browser_state,
    browser_state_event_timeout_s,
    captcha_wait_timeout_s,
    enrich_timed_out_browser_state,
    first_action_seconds,
    partial_agent_history,
)


def _click_agent() -> SimpleNamespace:
    action = SimpleNamespace(model_dump=lambda **_k: {"click": {"index": 3}})
    item = SimpleNamespace(
        model_output=SimpleNamespace(action=[action]),
        result=[],
        state=SimpleNamespace(url="https://excalidraw.com/"),
    )
    return SimpleNamespace(history=SimpleNamespace(history=[item]))


class StepBudgetTests(unittest.TestCase):
    def test_step_clock_covers_model_and_one_hold(self) -> None:
        budget = action_step_budget_s()
        self.assertGreaterEqual(
            budget,
            MVP_CAPTCHA_WAIT_S + MVP_STATE_TIMEOUT_S + MVP_LLM_TIMEOUT_S + MVP_HOLD_S,
        )
        self.assertLess(budget, 75)
        self.assertGreaterEqual(MVP_STEP_TIMEOUT_S, budget)
        self.assertLess(browser_state_event_timeout_s(4), 4)

    def test_captcha_wait_is_capped_at_a_couple_seconds(self) -> None:
        self.assertEqual(captcha_wait_timeout_s(None), MVP_CAPTCHA_WAIT_S)
        self.assertEqual(captcha_wait_timeout_s(120), MVP_CAPTCHA_WAIT_S)
        self.assertEqual(captcha_wait_timeout_s(1), 1)
        self.assertLessEqual(MVP_CAPTCHA_WAIT_S, 3)

    def test_timed_out_dom_keeps_opening_screenshot(self) -> None:
        summary = SimpleNamespace(state_error="Browser state capture timed out.", screenshot=None)
        out = enrich_timed_out_browser_state(
            summary,
            screenshot_b64="abc",
            url="https://excalidraw.com/",
            reason="abandoned",
        )
        self.assertEqual(out.screenshot, "abc")
        self.assertIn("viewport coordinates", out.state_error)

        healthy = SimpleNamespace(state_error=None, screenshot="live")
        self.assertIs(
            enrich_timed_out_browser_state(
                healthy,
                screenshot_b64="abc",
                url="https://excalidraw.com/",
                reason="abandoned",
            ),
            healthy,
        )

        empty = enrich_timed_out_browser_state(
            None,
            screenshot_b64="abc",
            url="https://excalidraw.com/",
            reason="abandoned",
        )
        self.assertEqual(empty.screenshot, "abc")
        self.assertEqual(empty.url, "https://excalidraw.com/")
        self.assertIn("viewport coordinates", empty.state_error)

    def test_slow_dom_returns_fallback_and_does_not_raise(self) -> None:
        async def slow() -> str:
            await asyncio.sleep(0.2)
            return "full-dom"

        result = asyncio.run(
            bounded_browser_state(slow, timeout_s=0.05, fallback="opening-shot")
        )
        self.assertEqual(result, "opening-shot")

    def test_fast_dom_is_kept(self) -> None:
        async def fast() -> str:
            return "full-dom"

        result = asyncio.run(bounded_browser_state(fast, timeout_s=1, fallback="opening-shot"))
        self.assertEqual(result, "full-dom")

    def test_first_action_requires_a_real_interact(self) -> None:
        empty = SimpleNamespace(history=SimpleNamespace(history=[]))
        self.assertIsNone(first_action_seconds(empty, t0=10.0, now=12.0, already=None))
        stamped = first_action_seconds(_click_agent(), t0=10.0, now=18.5, already=None)
        self.assertEqual(stamped, 8.5)
        self.assertEqual(
            first_action_seconds(_click_agent(), t0=10.0, now=40.0, already=stamped),
            8.5,
        )

    def test_partial_history_survives_a_cancelled_run(self) -> None:
        self.assertIsNone(partial_agent_history(None))
        self.assertIsNone(partial_agent_history(SimpleNamespace(history=SimpleNamespace(history=[]))))
        kept = partial_agent_history(_click_agent())
        self.assertEqual(len(kept.history), 1)

    def test_browser_state_event_uses_the_short_timeout(self) -> None:
        key = "TIMEOUT_BrowserStateRequestEvent"
        previous = os.environ.get(key)
        os.environ[key] = str(browser_state_event_timeout_s())
        try:
            from browser_use.browser.events import BrowserStateRequestEvent

            event = BrowserStateRequestEvent()
            self.assertAlmostEqual(float(event.event_timeout), browser_state_event_timeout_s())
            self.assertLess(float(event.event_timeout), 30)
        finally:
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


if __name__ == "__main__":
    unittest.main()
