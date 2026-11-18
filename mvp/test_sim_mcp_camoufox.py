"""Camoufox engine on the seeds (browser_engine, default camoufox). Unit tests run anywhere; the live test runs when
USERSIM_TEST_CAMOUFOX_WS points at a Camoufox Playwright server (scripts/vm/seed_camoufox_server.py)."""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from mvp.sim_mcp import limits, seed_backend as B, seed_probe, sessions as S, site_states as SS


class EngineSwitchTests(unittest.TestCase):
    def setUp(self):
        B._IN_USE.clear()
        B._HEALTH.clear()

    def test_default_is_camoufox_with_its_own_endpoints(self):
        vals = limits.parse(open(limits.BUNDLED).read())
        self.assertEqual(vals["browser_engine"], "camoufox")
        self.assertTrue(all(e.startswith("ws://127.0.0.1:193") for e in vals["seed_camoufox_endpoints"]))
        with mock.patch.dict(os.environ, {"MVP_MCP_BROWSER_ENGINE": "camoufox", "MVP_MCP_LIMITS_URL": "off"}):
            self.assertTrue(all(B.engine_of(e) == "camoufox" for e in B.endpoints()))
        with mock.patch.dict(os.environ, {"MVP_MCP_BROWSER_ENGINE": "chromium"}):
            self.assertTrue(all(B.engine_of(e) == "chromium" for e in B.endpoints()))

    def test_seed_index_and_labels(self):
        self.assertEqual(B.seed_index("ws://127.0.0.1:19321/usersim"), 1)
        self.assertEqual(B.seed_index("http://127.0.0.1:19222"), 2)
        slot = B.SeedSlot(endpoint="ws://127.0.0.1:19320/usersim", ws_url="ws://127.0.0.1:19320/usersim")
        self.assertEqual((slot.engine, slot.seed_label), ("camoufox", "seed-0"))
        eps = ["ws://127.0.0.1:19320/usersim#3", "ws://127.0.0.1:19321/usersim"]
        self.assertEqual(SS.seed_endpoint("usersim-signup-seed-1", eps), "ws://127.0.0.1:19321/usersim")

    def test_acquire_uses_the_active_engine(self):
        env = {"MVP_MCP_BROWSER_ENGINE": "camoufox", "MVP_MCP_SEED_WAIT_S": "0",
               "MVP_MCP_SEED_CAMOUFOX_ENDPOINTS": "ws://127.0.0.1:19321/usersim"}
        with mock.patch.dict(os.environ, env), mock.patch.object(B, "_healthy", side_effect=lambda e: e):
            slot = B.acquire()
        self.assertEqual((slot.engine, slot.connect_url), ("camoufox", "ws://127.0.0.1:19321/usersim"))


class ConnectTests(unittest.TestCase):
    def test_connect_dispatch(self):
        pw = SimpleNamespace(firefox=SimpleNamespace(connect=mock.AsyncMock(return_value="ff")),
                             chromium=SimpleNamespace(connect_over_cdp=mock.AsyncMock(return_value="cr")))
        cam = B.SeedSlot(endpoint="ws://127.0.0.1:19320/usersim", ws_url="ws://127.0.0.1:19320/usersim")
        cdp = B.SeedSlot(endpoint="http://127.0.0.1:19220", ws_url="ws://127.0.0.1:19220/devtools/browser/x")
        self.assertEqual(asyncio.run(S._connect(pw, cam)), "ff")
        pw.firefox.connect.assert_awaited_once_with("ws://127.0.0.1:19320/usersim", timeout=30000)
        self.assertEqual(asyncio.run(S._connect(pw, cdp)), "cr")
        self.assertEqual(asyncio.run(S._connect(pw, SimpleNamespace(connect_url="wss://bb"))), "cr")  # Browserbase

    def test_cdp_fallbacks_skip_firefox(self):
        page = mock.MagicMock()
        page.context.browser.browser_type.name = "firefox"
        self.assertFalse(S._is_chromium(page))
        page.context.browser.browser_type.name = "chromium"
        self.assertTrue(S._is_chromium(page))

    def test_probe_dispatch(self):
        with mock.patch.object(seed_probe, "probe_playwright_server", return_value="ws://x") as pps:
            self.assertEqual(seed_probe.probe("ws://127.0.0.1:19320/usersim"), "ws://x")
        pps.assert_called_once()


class SeedServerConfigTests(unittest.TestCase):
    def test_fixed_preset_is_chosen_once(self):
        import importlib.util
        import tempfile
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "seed_camoufox_server", Path(__file__).resolve().parents[1] / "scripts/vm/seed_camoufox_server.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "camoufox_preset.json"
            fake = SimpleNamespace(get_random_preset=mock.MagicMock(side_effect=[{"id": 1}, {"id": 2}]))
            with mock.patch.dict("sys.modules", {"camoufox": SimpleNamespace(), "camoufox.fingerprints": fake}):
                first = mod.fixed_preset(path, "linux")
                again = mod.fixed_preset(path, "linux")
            self.assertEqual(first, again)
            self.assertEqual(json.loads(path.read_text()), {"id": 1})
            self.assertEqual(fake.get_random_preset.call_count, 1)
            args = SimpleNamespace(port=9333, ws_path="usersim", os="linux", headless=True, executable_path="")
            with mock.patch.object(mod, "identity_dir", return_value=Path(d)):
                kw = mod.server_kwargs(args)
            self.assertEqual((kw["host"], kw["port"], kw["ws_path"]), ("127.0.0.1", 9333, "usersim"))
            self.assertEqual(kw["fingerprint_preset"], {"id": 1})


@unittest.skipUnless(os.environ.get("USERSIM_TEST_CAMOUFOX_WS"), "no Camoufox server (USERSIM_TEST_CAMOUFOX_WS)")
class CamoufoxLiveTests(unittest.TestCase):
    def test_probe_and_context(self):
        ws = os.environ["USERSIM_TEST_CAMOUFOX_WS"]
        self.assertEqual(seed_probe.probe(ws), ws)
        self.assertEqual(seed_probe.main(["x", ws, "15"]), 0)


if __name__ == "__main__":
    unittest.main()
