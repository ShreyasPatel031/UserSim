"""Seed-VM browser backend (mvp/sim_mcp/seed_backend.py) and its wiring in sessions.py."""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from mvp.sim_mcp import limits, seed_backend
from mvp.sim_mcp import sessions as S


class _Version(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/abc-123"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # noqa: D401
        pass


def _reset():
    seed_backend._IN_USE.clear()
    seed_backend._HEALTH.clear()


class LimitsTests(unittest.TestCase):
    def test_backend_defaults_to_seed_vm(self):
        vals = limits.parse(open(limits.BUNDLED).read())
        self.assertEqual(vals["browser_backend"], "seed_vm")
        self.assertTrue(vals["seed_cdp_endpoints"])
        self.assertGreaterEqual(vals["seed_sessions_per_seed"], 1)

    def test_string_values_parse(self):
        vals = limits.parse(json.dumps({"limits": {"browser_backend": {"value": "Browserbase"}}}))
        self.assertEqual(vals["browser_backend"], "browserbase")
        self.assertNotIn("browser_backend", limits.parse(json.dumps({"limits": {"browser_backend": {"value": 3}}})))

    def test_env_override_string(self):
        with mock.patch.dict("os.environ", {"MVP_MCP_BROWSER_BACKEND": "browserbase"}):
            self.assertEqual(S.browser_backend(), "browserbase")
        with mock.patch.dict("os.environ", {"MVP_MCP_BROWSER_BACKEND": "anything-else"}):
            self.assertEqual(S.browser_backend(), "seed_vm")


class WsUrlTests(unittest.TestCase):
    def test_ws_url_points_at_tunnel_end(self):
        srv = HTTPServer(("127.0.0.1", 0), _Version)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            port = srv.server_address[1]
            ws = seed_backend.ws_url_for(f"http://127.0.0.1:{port}")
            self.assertEqual(ws, f"ws://127.0.0.1:{port}/devtools/browser/abc-123")
        finally:
            srv.shutdown()


class SlotTests(unittest.TestCase):
    def setUp(self):
        _reset()
        self.env = mock.patch.dict("os.environ", {
            "MVP_MCP_SEED_CDP_ENDPOINTS": "http://127.0.0.1:19220,http://127.0.0.1:19221",
            "MVP_MCP_SEED_SESSIONS_PER_SEED": "2",
            "MVP_MCP_SEED_WAIT_S": "0",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_unhealthy_marker_forces_reprobe(self):
        seed_backend._HEALTH["http://127.0.0.1:19220"] = (9e18, "ws://cached")
        seed_backend.mark_unhealthy("http://127.0.0.1:19220")
        with mock.patch.object(seed_backend, "probe_ws", side_effect=OSError("wedged")):
            self.assertEqual(seed_backend._healthy("http://127.0.0.1:19220"), "")

    def test_spreads_then_busy_then_frees(self):
        with mock.patch.object(seed_backend, "_healthy", side_effect=lambda e: e.replace("http", "ws") + "/x"):
            slots = [seed_backend.acquire() for _ in range(4)]
            self.assertEqual(sorted(s.seed_label for s in slots), ["seed-0", "seed-0", "seed-1", "seed-1"])
            with self.assertRaises(seed_backend.SeedsBusy):
                seed_backend.acquire()
            seed_backend.release(slots[0])
            seed_backend.release(slots[0])  # idempotent
            again = seed_backend.acquire()
            self.assertEqual(again.endpoint, slots[0].endpoint)

    def test_dead_seed_skipped_and_none_raises(self):
        with mock.patch.object(seed_backend, "_healthy", side_effect=lambda e: "" if e.endswith("19220") else "ws://x"):
            self.assertEqual(seed_backend.acquire().seed_label, "seed-1")
        with mock.patch.object(seed_backend, "_healthy", return_value=""):
            with self.assertRaises(seed_backend.NoSeeds):
                seed_backend.acquire()

    def test_waits_for_a_slot(self):
        with mock.patch.dict("os.environ", {"MVP_MCP_SEED_SESSIONS_PER_SEED": "1", "MVP_MCP_SEED_WAIT_S": "5"}), \
                mock.patch.object(seed_backend, "_healthy", return_value="ws://x"):
            a, b = seed_backend.acquire(), seed_backend.acquire()
            threading.Timer(0.3, seed_backend.release, args=(a,)).start()
            c = seed_backend.acquire()
            self.assertEqual(c.endpoint, a.endpoint)
            seed_backend.release(b)
            seed_backend.release(c)


class ForbiddenHostTests(unittest.TestCase):
    def test_hosts(self):
        for h in ("producthunt.com", "www.producthunt.com", "api.producthunt.com", "metadata.google.internal",
                  "169.254.169.254", "10.128.0.5", "127.0.0.1", "localhost", "[::1]", "foo.internal"):
            self.assertTrue(S.seed_forbidden_host(h), h)
        for h in ("notion.so", "app.clickup.com", "8.8.8.8", "notproducthunt.com"):
            self.assertFalse(S.seed_forbidden_host(h), h)


class StartSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_producthunt_refused_on_seed(self):
        with mock.patch.dict("os.environ", {"MVP_MCP_BROWSER_BACKEND": "seed_vm"}), \
                mock.patch.object(S, "resolves_non_public", return_value=False), \
                mock.patch.object(S, "_open_browser") as opened:
            with self.assertRaises(S.SessionError):
                await S.start_session(product_url="https://www.producthunt.com", task="t", persona="p")
            opened.assert_not_called()

    async def test_busy_seeds_is_a_retry_not_a_failure(self):
        with mock.patch.dict("os.environ", {"MVP_MCP_BROWSER_BACKEND": "seed_vm"}), \
                mock.patch.object(S, "resolves_non_public", return_value=False), \
                mock.patch.object(S, "_create_seed", side_effect=seed_backend.SeedsBusy("all 1 seed(s) busy")):
            with self.assertRaises(S.SessionError) as ctx:
                await S.start_session(product_url="https://example.com", task="t", persona="p")
            self.assertIn("busy", str(ctx.exception))


class ReviveTests(unittest.IsolatedAsyncioTestCase):
    def _sim(self, connected: bool):
        sim = S.SimSession(id="x" * 32, study=mock.MagicMock(), product_url="https://example.com", task="t", persona="p")
        sim.bb = seed_backend.SeedSlot(endpoint="http://127.0.0.1:19220", ws_url="ws://127.0.0.1:19220/d")
        sim.browser = mock.MagicMock()
        sim.browser.is_connected.return_value = connected
        sim.page = mock.MagicMock()
        sim.page.is_closed.return_value = False
        return sim

    async def test_no_op_when_connected(self):
        self.assertFalse(await S.revive(self._sim(True)))

    async def test_gives_up_after_max(self):
        sim = self._sim(False)
        sim.reconnects = S.MAX_RECONNECTS
        with self.assertRaises(S.SessionError):
            await S.revive(sim)

    async def test_unreachable_seed_is_session_error(self):
        sim = self._sim(False)
        with mock.patch.object(seed_backend, "probe_ws", side_effect=OSError("refused")):
            with self.assertRaises(S.SessionError) as ctx:
                await S.revive(sim)
        self.assertIn("dropped", str(ctx.exception))
        self.assertEqual(sim.reconnects, 1)

    def test_browserbase_never_revives(self):
        sim = self._sim(False)
        sim.bb = mock.MagicMock(backend="")
        self.assertFalse(S._browser_dropped(sim))


class LimitsRouteTests(unittest.TestCase):
    def test_limits_route_reports_browsers(self):
        from mvp.test_sim_mcp_auth import _app

        with mock.patch.object(seed_backend, "_healthy", return_value=""):
            body = _app({}).get("/api/mcp/limits").json()
        self.assertEqual(body["browsers"]["backend"], "seed_vm")
        self.assertEqual(body["browsers"]["seeds"][0]["healthy"], False)



class SeedProofTests(unittest.TestCase):
    """Study ab3c9656 (Nov 17, first seed study): proof failed on all 108 cells because live_view_offered wanted a
    Browserbase live view URL, which seeds never have."""

    def _row(self, backend="seed_vm", live=""):
        trace = [{"step": i, "action": a, "url": u, "screenshot_url": f"/x/step_{i}.png"}
                 for i, (a, u) in enumerate([("Opened https://tally.so", "https://tally.so/"),
                                              ("click — (10, 20)", "https://tally.so/create")])]
        return {"agent_id": "a1", "site_url": "https://tally.so", "page_url": "https://tally.so/", "trace": trace,
                "browser_backend": backend, "live_view_url": live, "task_prompt": "make a form", "last_action": "click"}

    def _proof(self, row, shots_ok=True):
        from mvp.sim_mcp import report as R

        study = {"id": "s1", "driver": S.DRIVER, "test_mode": False}
        with mock.patch.object(R, "_shot_ok", return_value=shots_ok):
            return {c["name"]: c for c in R.proof_checks(study, row, "ok")["checks"]}

    def test_seed_run_with_real_frames_is_watchable(self):
        c = self._proof(self._row())["live_view_offered"]
        self.assertTrue(c["pass"], c)
        self.assertIn("seed_vm", c["detail"])

    def test_seed_run_without_frames_is_not(self):
        self.assertFalse(self._proof(self._row(), shots_ok=False)["live_view_offered"]["pass"])

    def test_browserbase_still_needs_its_live_view(self):
        self.assertFalse(self._proof(self._row(backend=""))["live_view_offered"]["pass"])
        self.assertTrue(self._proof(self._row(backend="", live="https://www.browserbase.com/x"))["live_view_offered"]["pass"])


if __name__ == "__main__":
    unittest.main()
