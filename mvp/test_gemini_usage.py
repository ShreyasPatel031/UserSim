"""gemini_chat logs input/output tokens per call and feeds track_usage (Vertex mocked)."""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import unittest
from unittest import mock

import httpx

from capability import gemini_config as gc

REPLY = {
    "candidates": [{"content": {"parts": [{"text": "{\"ok\": true}"}]}}],
    "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": 80, "thoughtsTokenCount": 20, "totalTokenCount": 1300},
}


class _Creds:
    token = "t"


def _client_factory(handler):
    real = httpx.AsyncClient

    def make(*a, **kw):
        kw.pop("transport", None)
        return real(*a, transport=httpx.MockTransport(handler), **kw)

    return make


class GeminiUsageTests(unittest.TestCase):
    def _chat(self, handler, env=None):
        out = io.StringIO()
        env = {"GOOGLE_CLOUD_PROJECT": "p", "VERTEX_LOCATION": "global", "MVP_LLM_LOG_TOKENS": "1", **(env or {})}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(gc, "cached_vertex_credentials", lambda: _Creds()), \
                mock.patch.object(gc.httpx, "AsyncClient", _client_factory(handler)), \
                contextlib.redirect_stdout(out), gc.track_usage() as rows:
            text = asyncio.run(gc.gemini_chat([{"role": "user", "content": "hi"}], model="gemini-2.5-flash", max_retries=1))  # pragma: allowlist secret
        return text, rows, out.getvalue()

    def test_each_call_logs_tokens_and_records_a_usage_row(self):
        text, rows, log = self._chat(lambda req: httpx.Response(200, json=REPLY))
        self.assertEqual(text, '{"ok": true}')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["model"], "gemini-2.5-flash")  # pragma: allowlist secret
        self.assertEqual((rows[0]["input_tokens"], rows[0]["output_tokens"]), (1200, 100))
        self.assertRegex(log, r"\[gemini\] tokens gemini-2\.5-flash in=1200 out=100 after \d+\.\ds")

    def test_logging_can_be_turned_off_but_usage_is_still_recorded(self):
        _text, rows, log = self._chat(lambda req: httpx.Response(200, json=REPLY), env={"MVP_LLM_LOG_TOKENS": "0"})
        self.assertEqual(log, "")
        self.assertEqual(len(rows), 1)

    def test_a_reply_without_usage_metadata_counts_zero(self):
        reply = {"candidates": REPLY["candidates"]}
        _text, rows, log = self._chat(lambda req: httpx.Response(200, json=reply))
        self.assertEqual((rows[0]["input_tokens"], rows[0]["output_tokens"]), (0, 0))
        self.assertIn("in=0 out=0", log)

    def test_usage_outside_track_usage_is_not_collected(self):
        with mock.patch.dict(os.environ, {"MVP_LLM_LOG_TOKENS": "0"}):
            gc._note_usage("gemini-2.5-flash", REPLY, 1.0)  # pragma: allowlist secret
        with gc.track_usage() as rows:
            pass
        self.assertEqual(rows, [])

    def test_cost_uses_the_longest_matching_price(self):
        rows = [
            {"model": "gemini-2.5-flash-lite", "input_tokens": 1_000_000, "output_tokens": 1_000_000},  # pragma: allowlist secret
            {"model": "gemini-2.5-flash", "input_tokens": 1_000_000, "output_tokens": 0},  # pragma: allowlist secret
        ]
        self.assertAlmostEqual(gc.estimate_cost_usd(rows), 0.10 + 0.40 + 0.30)
        self.assertIsNone(gc.estimate_cost_usd([{"model": "mystery-model", "input_tokens": 1}]))
        self.assertEqual(gc.estimate_cost_usd([]), 0.0)


if __name__ == "__main__":
    unittest.main()
