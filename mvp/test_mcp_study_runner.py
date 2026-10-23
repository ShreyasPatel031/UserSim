"""Unit tests for scripts/mcp_study_runner_lib (no network)."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import mcp_study_runner_lib as lib  # noqa: E402


class CostMathTests(unittest.TestCase):
    def test_usage_to_usd_regular_and_cache(self) -> None:
        usage = SimpleNamespace(
            input_tokens=1000,
            output_tokens=200,
            cache_creation_input_tokens=400,
            cache_read_input_tokens=500,
        )
        # regular = 1000 - 400 - 500 = 100
        expected = (
            100 * lib.usd_per_mtok("input")
            + 400 * lib.usd_per_mtok("input") * 1.25
            + 500 * lib.usd_per_mtok("input") * 0.1
            + 200 * lib.usd_per_mtok("output")
        )
        self.assertAlmostEqual(lib.usage_to_usd(usage), expected, places=12)


class SpendCapTests(unittest.TestCase):
    def test_gate_stops_at_max_usd(self) -> None:
        gate = lib.SpendGate(max_usd=0.01, max_retries=50)
        usage = SimpleNamespace(
            input_tokens=20_000,
            output_tokens=0,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )
        lib.usage_to_usd(usage)
        gate.record_usage(usage)
        self.assertTrue(gate.over_cap())
        self.assertEqual(gate.stop_reason, "runner spend cap")


class PilotTests(unittest.TestCase):
    def test_pilot_one_per_site(self) -> None:
        cells = [
            {"cell_id": "a", "site": "https://a"},
            {"cell_id": "b", "site": "https://a"},
            {"cell_id": "c", "site": "https://b"},
            {"cell_id": "d", "site": "https://c"},
        ]
        pilots = lib.pilot_cells_for_study(cells)
        self.assertEqual({c["cell_id"] for c in pilots}, {"a", "c", "d"})

    def test_pilot_abort_when_projection_over_cap(self) -> None:
        abort, projected = lib.pilot_should_abort(mean_cell_usd=0.25, total_cells=108, max_usd=20.0)
        self.assertTrue(abort)
        self.assertAlmostEqual(projected, 27.0)
        abort2, _ = lib.pilot_should_abort(mean_cell_usd=0.05, total_cells=108, max_usd=20.0)
        self.assertFalse(abort2)


class RetryTests(unittest.TestCase):
    def test_max_attempt_constants(self) -> None:
        self.assertEqual(lib.MAX_MODEL_ATTEMPTS, 3)
        self.assertEqual(lib.MAX_TOOL_ATTEMPTS, 3)

    def test_non_retryable_4xx(self) -> None:
        self.assertFalse(lib.is_retryable_error(RuntimeError("HTTP 403 forbidden")))
        self.assertFalse(lib.is_retryable_error(ValueError("validation error: bad field")))
        self.assertTrue(lib.is_retryable_error(RuntimeError("HTTP 429 rate limit")))

    def test_retry_budget_stops_gate(self) -> None:
        gate = lib.SpendGate(max_usd=100.0, max_retries=2)
        self.assertTrue(gate.record_retry())
        self.assertTrue(gate.record_retry())
        self.assertFalse(gate.record_retry())
        self.assertTrue(gate.over_cap())


class AppendOnlyHistoryTests(unittest.TestCase):
    def test_earlier_message_objects_unchanged_between_turns(self) -> None:
        state = lib.TranscriptState()
        state.append_user("Begin")
        before_ids = lib.snapshot_message_objects(state.messages)
        before_snapshots = [copy.deepcopy(m) for m in state.messages]

        state.append_assistant([{"type": "text", "text": "ok"}])
        state.append_observe_tool_result(
            "tu1",
            [SimpleNamespace(type="text", text="url=https://x title=Hi page=hello", mimeType=None, data=None)],
        )
        mid_ids = lib.snapshot_message_objects(state.messages[:1])
        self.assertEqual(before_ids, mid_ids)
        for orig, cur in zip(before_snapshots, state.messages[:1]):
            self.assertEqual(orig, cur)

        state.append_assistant([{"type": "tool_use", "id": "tu2", "name": "usersim_observe", "input": {}}])
        state.append_observe_tool_result(
            "tu2",
            [SimpleNamespace(type="text", text="url=https://y title=Bye", mimeType=None, data=None)],
        )
        self.assertEqual(before_ids, lib.snapshot_message_objects(state.messages[:1]))
        for orig, cur in zip(before_snapshots, state.messages[:1]):
            self.assertEqual(orig, cur)

    def test_screenshot_only_on_api_copy_not_stored_in_old_results(self) -> None:
        png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        state = lib.TranscriptState()
        state.append_user("Begin")
        state.append_assistant([{"type": "tool_use", "id": "t1", "name": "usersim_observe", "input": {}}])
        state.append_observe_tool_result(
            "t1",
            [
                SimpleNamespace(type="text", text="url=https://a", mimeType=None, data=None),
                SimpleNamespace(type="image", mimeType="image/png", text=None, data=png),
            ],
        )
        stored = state.messages[-1]["content"][0]["content"]
        self.assertFalse(any(b.get("type") == "image" for b in stored))
        api = state.inject_screenshot_for_api(state.messages)
        last_tr = api[-1]["content"][0]
        self.assertTrue(any(b.get("type") == "image" for b in last_tr["content"]))


if __name__ == "__main__":
    unittest.main()


def test_stall_summary_counts_repeated_actions_and_captcha_steps():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from mcp_study_runner import stall_summary

    steps = [{"tool": "usersim_act", "action": "click", "url": "u", "captcha": "x"}] * 4 + [{"tool": "usersim_observe"}]
    assert stall_summary(steps) == {"max_repeat_same_action_and_url": 4, "captcha_steps": 4}
