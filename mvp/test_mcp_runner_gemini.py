"""Dry tests (no network) of the Gemini per-cell driver: scripts/mcp_runner_gemini.py inside mcp_study_runner.run_cell.

A fake Vertex client returns real google.genai response objects; the MCP server is faked at the runner's tool() and
listing() seams. Checks: screenshot in, exactly one action out, forced function calling, spend accounting, the cell
spend cap, and the finish/give-up rules.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from google.genai import types  # noqa: E402

import mcp_runner_gemini as G  # noqa: E402
import mcp_study_runner as R  # noqa: E402
import mcp_study_runner_lib as lib  # noqa: E402


def _png_b64() -> str:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1280, 800), (255, 255, 255)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


PNG = _png_b64()


def _resp(*calls: tuple[str, dict], text: str = "", prompt=1000, out=50, thoughts=100) -> types.GenerateContentResponse:
    parts = []
    if text:
        parts.append(types.Part(text=text))
    for name, args in calls:
        parts.append(types.Part(function_call=types.FunctionCall(name=name, args=args), thought_signature=b"sig"))
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt, candidates_token_count=out, thoughts_token_count=thoughts),
    )


class FakeClient:
    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.requests: list[dict] = []
        self.models = SimpleNamespace(generate_content=self._gen)

    def _gen(self, *, model, contents, config):
        self.requests.append({"model": model, "contents": contents, "config": config})
        return self.script.pop(0) if self.script else _resp(("usersim_finish", {"outcome": "completed", "notes": "done"}))


def _mcp_tools():
    schema = {"type": "object", "properties": {"session_id": {"type": "string"},
                                                "action": {"type": "object", "properties": {"type": {"type": "string"}}}},
              "required": ["session_id"]}
    return SimpleNamespace(tools=[SimpleNamespace(name=n, description=f"{n} tool", inputSchema=schema)
                                  for n in ("usersim_observe", "usersim_act", "usersim_finish", "usersim_start_session")])


class FakeServer:
    """The MCP server as the runner sees it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def tool(self, name, args, gate, retries=3):
        self.calls.append((name, dict(args)))
        txt = lambda t: SimpleNamespace(type="text", text=t)  # noqa: E731
        if name == "usersim_start_session":
            return SimpleNamespace(content=[txt(json.dumps({"session_id": "sess1"}))])
        if name in ("usersim_observe", "usersim_act"):
            return SimpleNamespace(content=[txt(json.dumps({"url": "https://example.com/signup", "step": len(self.calls)})),
                                            SimpleNamespace(type="image", mimeType="image/png", data=PNG)])
        if name == "usersim_finish":
            return SimpleNamespace(content=[txt(json.dumps({"finished": True, "outcome": args.get("outcome")}))])
        raise AssertionError(name)

    async def listing(self, what, *args):
        if what == "tools":
            return _mcp_tools()
        return SimpleNamespace(messages=[SimpleNamespace(content=SimpleNamespace(text="You are a simulated user."))])


def _run(script, *, max_turns=10, max_cell_usd=0.5, max_usd=5.0):
    client, server = FakeClient(script), FakeServer()
    gate = lib.SpendGate(max_usd=max_usd, max_retries=5)
    cell = {"cell_id": "t1__p1__s1", "site": "https://example.com", "persona": "Ana", "task": "Sign up"}
    with tempfile.TemporaryDirectory() as d, \
            mock.patch.object(R, "tool", server.tool), mock.patch.object(R, "listing", server.listing), \
            mock.patch.object(R, "MODEL", "gemini-2.5-flash"):
        log = asyncio.run(R.run_cell("study1", cell, max_turns, max_cell_usd, Path(d), G.GeminiDriver(client), gate))
        saved = json.loads((Path(d) / "t1__p1__s1.json").read_text())
    return log, saved, client, server, gate


class RunCellTests(unittest.TestCase):
    def test_observe_act_finish(self):
        log, saved, client, server, gate = _run([
            _resp(("usersim_observe", {})),
            _resp(("usersim_act", {"action": {"type": "click"}}), text="Click Sign up"),
            _resp(("usersim_finish", {"outcome": "completed", "notes": "signed up"})),
        ])
        self.assertEqual([c[0] for c in server.calls],
                         ["usersim_start_session", "usersim_observe", "usersim_act", "usersim_finish"])
        self.assertTrue(all(c[1].get("session_id") == "sess1" for c in server.calls[1:]))
        self.assertNotIn("error", log)
        self.assertEqual(len(client.requests), 3)
        self.assertEqual(saved["steps"][1]["thought"], "Click Sign up")
        # spend: 3 calls x (1000 in @0.30 + 150 out @2.50) / 1M
        self.assertAlmostEqual(gate.total_usd, 3 * (1000 * 0.30 + 150 * 2.50) / 1e6, places=9)
        self.assertAlmostEqual(log["model_usd"], round(gate.total_usd, 6), places=6)

    def test_screenshot_in_and_forced_single_call(self):
        _, _, client, _, _ = _run([
            _resp(("usersim_observe", {})),
            _resp(("usersim_finish", {"outcome": "completed"})),
        ])
        first, second = client.requests
        cfg = second["config"]
        self.assertEqual(cfg.tool_config.function_calling_config.mode, types.FunctionCallingConfigMode.ANY)
        self.assertTrue(cfg.automatic_function_calling.disable)
        self.assertEqual(cfg.system_instruction, "You are a simulated user.")
        names = [f.name for f in cfg.tools[0].function_declarations]
        self.assertEqual(sorted(names), ["usersim_act", "usersim_finish", "usersim_observe"])  # SUB_TOOLS only
        self.assertFalse(any(p.inline_data for c in first["contents"] for p in c.parts))  # no screenshot yet
        last_user = second["contents"][-1]
        self.assertEqual(last_user.role, "user")
        self.assertEqual(last_user.parts[0].function_response.name, "usersim_observe")
        self.assertTrue(any(p.inline_data and p.inline_data.mime_type.startswith("image/") for p in last_user.parts))
        model_turn = second["contents"][-2]
        self.assertEqual(model_turn.role, "model")
        self.assertEqual(model_turn.parts[0].thought_signature, b"sig")  # replayed

    def test_two_calls_in_one_turn_run_only_the_first(self):
        _, saved, client, server, _ = _run([
            _resp(("usersim_act", {"action": {"type": "click"}}), ("usersim_act", {"action": {"type": "type"}})),
            _resp(("usersim_finish", {"outcome": "completed"})),
        ])
        acts = [c for c in server.calls if c[0] == "usersim_act"]
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0][1]["action"], {"type": "click"})
        calls_in_history = [p for c in client.requests[1]["contents"] for p in c.parts if p.function_call]
        self.assertEqual(len(calls_in_history), 1)

    def test_turn_cap_gives_up(self):
        log, _, _, server, _ = _run([_resp(("usersim_observe", {}))] * 5, max_turns=3)
        fin = [c for c in server.calls if c[0] == "usersim_finish"]
        self.assertEqual(len(fin), 1)
        self.assertEqual(fin[0][1]["outcome"], "gave_up")
        self.assertIn("3-turn cap", fin[0][1]["notes"])

    def test_cell_spend_cap_stops(self):
        big = lambda: _resp(("usersim_observe", {}), prompt=400_000, out=0, thoughts=0)  # $0.12 a turn  # noqa: E731
        log, _, client, server, _ = _run([big() for _ in range(10)], max_cell_usd=0.25)
        self.assertEqual(len(client.requests), 3)  # stops once the cell is over $0.25
        fin = [c for c in server.calls if c[0] == "usersim_finish"]
        self.assertEqual(fin[-1][1]["outcome"], "gave_up")

    def test_run_spend_cap_stops(self):
        big = lambda: _resp(("usersim_observe", {}), prompt=400_000, out=0, thoughts=0)  # noqa: E731
        log, _, client, server, gate = _run([big() for _ in range(10)], max_usd=0.2)
        self.assertTrue(gate.over_cap())
        self.assertLessEqual(len(client.requests), 2)
        fin = [c for c in server.calls if c[0] == "usersim_finish"]
        self.assertEqual(fin[-1][1]["outcome"], "gave_up")
        self.assertIn(R.STOP_NOTE, fin[-1][1]["notes"])


class TranslationTests(unittest.TestCase):
    def test_error_results_and_text(self):
        msgs = [
            {"role": "user", "content": "Begin."},
            {"role": "assistant", "content": [{"type": "text", "text": "look"},
                                              {"type": "tool_use", "id": "a", "name": "usersim_act", "input": {"x": 1}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "is_error": True,
                                          "content": [{"type": "text", "text": "boom", "cache_control": {"type": "ephemeral"}}]}]},
            {"role": "user", "content": "Use a tool."},
        ]
        contents = G.to_gemini_contents(msgs)
        self.assertEqual([c.role for c in contents], ["user", "model", "user"])  # consecutive user turns merged
        fr = contents[2].parts[0].function_response
        self.assertEqual((fr.name, fr.response), ("usersim_act", {"error": "boom"}))
        self.assertEqual(contents[2].parts[1].text, "Use a tool.")

    def test_schema_cache_control_dropped(self):
        tools = G.to_gemini_tools([{"name": "t", "description": "d", "cache_control": {"type": "ephemeral"},
                                    "input_schema": {"type": "object", "properties": {}}}])
        self.assertEqual(tools[0].function_declarations[0].parameters_json_schema, {"type": "object", "properties": {}})

    def test_usage_pricing(self):
        meta = types.GenerateContentResponseUsageMetadata(prompt_token_count=2_000_000, cached_content_token_count=1_000_000,
                                                          candidates_token_count=100_000, thoughts_token_count=100_000)
        self.assertAlmostEqual(G.usage_to_usd(meta), 0.30 + 0.075 + 0.5)
        self.assertEqual(lib.usage_to_usd(G.Usage(usd=0.42)), 0.42)


class DriverChoiceTests(unittest.TestCase):
    def test_default_driver_is_gemini_and_claude_is_opt_in(self):
        import importlib
        import os

        with mock.patch.dict(os.environ, {"RUNNER_DRIVER": "", "RUNNER_MODEL": ""}):
            r = importlib.reload(R)
            self.assertEqual((r.DRIVER, r.MODEL), ("gemini", "gemini-2.5-flash"))
        with mock.patch.dict(os.environ, {"RUNNER_DRIVER": "claude", "RUNNER_MODEL": ""}):
            r = importlib.reload(R)
            self.assertEqual((r.DRIVER, r.MODEL, r.MAX_TOKENS), ("claude", "claude-haiku-5-5", 4096))
        with mock.patch.dict(os.environ, {"RUNNER_DRIVER": "gemini", "RUNNER_MODEL": "claude-haiku-5-5"}):
            r = importlib.reload(R)
            with self.assertRaises(SystemExit):
                r.make_llm()
        importlib.reload(R)

if __name__ == "__main__":
    unittest.main()


class ResumeTests(unittest.TestCase):
    """Nov 17: an overloaded MCP server (httpx ConnectError) used up the retry budget; 43 never-started cells were
    written as 'stopped: runner spend cap' <cell>.json and --resume skipped them as done."""

    def test_crash_before_a_session_is_not_saved_as_done(self):
        gate = lib.SpendGate(max_usd=5.0, max_retries=0)

        async def down(name, args, gate_, retries=3):
            gate_.record_retry()  # budget 0: the gate stops, as after a burst of ConnectErrors
            raise RuntimeError(f"{name}: ConnectError: All connection attempts failed")

        cell = {"cell_id": "t1__p1__product", "site": "https://example.com", "persona": "p", "task": "t"}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(R, "tool", down):
            log = asyncio.run(R.run_cell("s1", cell, 5, 0.5, Path(d), None, gate))
            self.assertFalse((Path(d) / "t1__p1__product.json").exists())
            self.assertTrue(json.loads((Path(d) / "t1__p1__product.notrun.json").read_text())["not_run"])
            self.assertFalse(R.cell_done(Path(d), "t1__p1__product"))
            self.assertIn("retry budget", log["finish"])  # says why, not 'spend cap'

    def test_resume_runs_never_started_cells_only(self):
        cells = [{"cell_id": c, "site": "https://example.com", "persona": "p", "task": "t"} for c in ("a", "b", "c", "d")]
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "s1"
            out.mkdir()
            (out / "study.json").write_text(json.dumps({"study_id": "s1", "cells": cells}))
            (out / "a.json").write_text(json.dumps({"session_id": "x", "finish": "ok"}))  # ran
            (out / "b.json").write_text(json.dumps({"finish": R.STOP_NOTE, "error": R.STOP_NOTE}))  # old runner, never ran
            (out / "c.notrun.json").write_text(json.dumps({"not_run": True}))
            ran = []

            async def fake_cell(study_id, cell, *a, **k):
                ran.append(cell["cell_id"])
                log = {"session_id": "new", "cell": cell}
                R._save_cell(a[2], cell, log)
                return log

            async def fake_tool(name, args, gate_, retries=3):
                return SimpleNamespace(content=[SimpleNamespace(type="text", text="report")])

            gate = lib.SpendGate(max_usd=5.0, max_retries=5)
            with mock.patch.object(R, "run_cell", fake_cell), mock.patch.object(R, "tool", fake_tool), \
                    mock.patch.object(R, "_save_server_study", lambda *a: None):
                summary = asyncio.run(R.run_study("https://example.com", 4, 5, 0.5, Path(d), None, gate, resume="s1"))
            self.assertEqual(sorted(ran), ["b", "c", "d"])
            self.assertEqual((summary["finished"], summary["not_run"]), (4, 0))
            self.assertFalse((out / "c.notrun.json").exists())


class CompetitorTests(unittest.TestCase):
    def test_competitors_go_to_start_study(self):
        seen = {}

        async def fake_tool(name, args, gate_, retries=3):
            if name == "usersim_start_study":
                seen.update(args)
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps({"error": "stop here"}))])
            raise AssertionError(name)

        gate = lib.SpendGate(max_usd=5.0, max_retries=5)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(R, "tool", fake_tool):
            asyncio.run(R.run_study("https://tally.so", 4, 5, 0.5, Path(d), None, gate,
                                    competitors=["https://fillout.com", "https://typeform.com"]))
        self.assertEqual(seen["product_url"], "https://tally.so")
        self.assertEqual(seen["competitors"], ["https://fillout.com", "https://typeform.com"])
