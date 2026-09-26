"""Action steps use the configured flash model, not its lite sibling."""

from __future__ import annotations

import os
import unittest

from mvp.browser_agent import action_model_name


class ActionModelNameTest(unittest.TestCase):
    def setUp(self) -> None:
        self._prev = {
            key: os.environ.get(key)
            for key in ("MVP_AGENT_ACTION_MODEL", "MVP_BROWSER_MODEL", "MVP_LLM_MODEL")
        }

    def tearDown(self) -> None:
        for key, value in self._prev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_does_not_downgrade_flash_to_lite(self) -> None:
        os.environ.pop("MVP_AGENT_ACTION_MODEL", None)
        os.environ["MVP_BROWSER_MODEL"] = "gemini-test-flash"
        os.environ["MVP_LLM_MODEL"] = "gemini-test-flash"
        self.assertEqual(action_model_name(), "gemini-test-flash")
        self.assertNotIn("lite", action_model_name().lower())

    def test_explicit_override_wins(self) -> None:
        os.environ["MVP_BROWSER_MODEL"] = "gemini-test-flash"
        os.environ["MVP_AGENT_ACTION_MODEL"] = "gemini-test-flash-lite"
        self.assertEqual(action_model_name(), "gemini-test-flash-lite")
        self.assertEqual(action_model_name("gemini-other"), "gemini-other")


if __name__ == "__main__":
    unittest.main()
