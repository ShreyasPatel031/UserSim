"""The gateway: ladder order, Apify only after every cheaper route and with ALLOW_APIFY=1, the budget cap stopping a
job, the spend log, actor runs, and the localhost service (caps clamped, errors mapped)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import fetchgate
from fetchgate import gate, ladder, ledger as L, service

REAL = (200, "<title>Reviews</title>" + "x" * 30000)
WALL = (403, "<title>Just a moment...</title>")
URL = "https://www.capterra.com/p/1/X/reviews/"
RESI = "http://u:p@gw.example.com:823"


class GateCase(unittest.TestCase):
    def setUp(self):
        ladder._BLOCKED.clear()
        gate._WALLS.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "fetches.jsonl"
        L.set_ledger(L.Ledger(self.log))
        self.env = mock.patch.dict(os.environ, {"FETCHGATE_CREDENTIALS": str(Path(self.tmp.name) / "none"),
                                                "MVP_DISCOVERY_KEYS_FILE": str(Path(self.tmp.name) / "none.json"),
                                                "HOME": self.tmp.name, "FETCH_JOB": "test-job"})
        self.env.start()
        for k in ("ALLOW_APIFY", "FETCH_BUDGET_USD", "FETCHGATE_URL", "FETCHGATE_SERVICE", "FETCHGATE_DAILY_USD",
                  "PROXY_URL", "APIFY_TOKEN", "FETCHGATE_APIFY", "FETCHGATE_MAX_JOB_USD"):
            os.environ.pop(k, None)
        self.calls: list[str] = []

    def tearDown(self):
        self.env.stop()
        L.set_ledger(None)
        self.tmp.cleanup()

    def fake(self, passes: set[str], nbytes: int = 70_000, statuses: dict[str, tuple[int, str]] | None = None):
        def run(tier, url, residential, meter=None, apify_token=None):
            self.calls.append(tier)
            if meter is not None:
                meter["bytes"] = nbytes
            if statuses and tier in statuses:
                return statuses[tier]
            return REAL if tier in passes else WALL
        return mock.patch.object(ladder, "tier_fetch", side_effect=run)

    def rows(self) -> list[dict]:
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []


class LadderOrderTest(GateCase):
    def test_cheapest_route_that_passes_and_blocked_routes_are_skipped_next_time(self):
        with self.fake({"residential"}):
            out = fetchgate.fetch(URL, creds_override={"PROXY_URL": RESI})
            self.assertEqual((out["status"], out["route"]), (200, "residential"))
            self.assertEqual(self.calls, ["vm", "vm_camoufox", "residential"])
            self.assertAlmostEqual(out["usd"], 0.00007)
            self.calls.clear()
            fetchgate.fetch(URL + "?page=2", creds_override={"PROXY_URL": RESI})
            self.assertEqual(self.calls, ["residential"])  # VM routes hit a wall on this site a moment ago

    def test_every_attempt_is_logged_with_route_bytes_and_cost(self):
        with self.fake({"residential"}):
            fetchgate.fetch(URL, creds_override={"PROXY_URL": RESI})
        rows = self.rows()
        self.assertEqual([r["route"] for r in rows], ["vm", "vm_camoufox", "residential"])
        self.assertEqual([r["ok"] for r in rows], [False, False, True])
        self.assertTrue(all(r["job"] == "test-job" and r["bytes"] == 70_000 and "ts" in r for r in rows))
        self.assertAlmostEqual(rows[-1]["job_usd"], 0.00007)
        s = fetchgate.job_summary("test-job")
        self.assertEqual((s["items_fetched"], s["routes"]["residential"]["passed"]), (1, 1))
        self.assertAlmostEqual(s["usd_per_item"], 0.00007)

    def test_errors_and_timeouts_fall_through_without_blocking_the_route(self):
        def run(tier, url, residential, meter=None, apify_token=None):
            if tier == "vm":
                raise TimeoutError("slow via http://u:secret@gw.example.com:823")
            return REAL
        with mock.patch.object(ladder, "tier_fetch", side_effect=run):
            out = fetchgate.fetch("https://www.trustradius.com/products/x/reviews")
        self.assertEqual(out["route"], "vm_camoufox")
        self.assertNotIn(("trustradius.com", "vm"), ladder._BLOCKED)
        self.assertNotIn("secret", json.dumps(out) + self.log.read_text())

    def test_not_found_ends_the_ladder_and_rate_limits_do_not_block(self):
        with self.fake(set(), statuses={"vm": (404, "<title>Not found</title>")}):
            out = fetchgate.fetch("https://www.producthunt.com/@nobody/upvotes", creds_override={"PROXY_URL": RESI})
        self.assertEqual((out["status"], out["route"], self.calls), (404, "vm", ["vm"]))
        with self.fake(set(), statuses={"vm": (429, "slow down")}):
            fetchgate.fetch("https://api.fxtwitter.com/x", routes=("vm",))
        self.assertNotIn(("api.fxtwitter.com", "vm"), ladder._BLOCKED)

    def test_browser_mode_starts_with_camoufox_on_the_vm_ip(self):
        seen = []

        def load(url, proxy, **kw):
            seen.append((proxy, kw["scroll"]))
            kw["meter"]["bytes"] = 2_000_000
            return {"status": 200, "html": REAL[1], "final_url": url, "scrolls": 3, "responses": [{"url": "x"}]}
        with mock.patch("fetchgate.browser.load", side_effect=load), \
                mock.patch.object(ladder, "ensure_tool", return_value={"ok": True}):
            out = fetchgate.fetch("https://www.producthunt.com/@a/upvotes", scroll=True, creds_override={"PROXY_URL": RESI})
        self.assertEqual((out["route"], out["usd"], out["scrolls"], seen), ("vm_camoufox", 0.0, 3, [(None, True)]))


    def test_scroll_tries_residential_chromium_then_camoufox_and_rotating_ips_need_three_walls(self):
        engines = []

        def load(url, proxy, **kw):
            engines.append((kw["engine"], bool(proxy)))
            kw["meter"]["bytes"] = 1_000_000
            if kw["engine"] == "camoufox" and proxy:
                return {"status": 200, "html": REAL[1], "final_url": url, "scrolls": 5, "responses": []}
            return {"status": 403, "html": WALL[1], "final_url": url, "scrolls": 0, "responses": []}
        with mock.patch("fetchgate.browser.load", side_effect=load), \
                mock.patch.object(ladder, "ensure_tool", return_value={"ok": True}):
            for i in range(4):
                out = fetchgate.fetch(f"https://www.producthunt.com/@u{i}/upvotes", scroll=True,
                                      creds_override={"PROXY_URL": RESI})
                self.assertEqual(out["route"], "residential_camoufox")
        self.assertEqual(engines[:3], [("camoufox", False), ("chromium", True), ("camoufox", True)])
        # the VM IP is walled after one 403; residential Chromium only after its third in a row
        self.assertEqual(engines.count(("camoufox", False)), 1)
        self.assertEqual(engines.count(("chromium", True)), 3)
        self.assertIn(("producthunt.com", "residential_chromium"), ladder._BLOCKED)


class ApifyGateTest(GateCase):
    def test_apify_never_runs_without_allow_apify(self):
        with self.fake(set()), mock.patch("fetchgate.creds.apify_token", return_value="tok"):
            out = fetchgate.fetch(URL, creds_override={"PROXY_URL": RESI})
        self.assertNotIn("apify_unblocker", self.calls)
        self.assertEqual(out["route"], "")
        self.assertIn({"route": "apify_unblocker", "skipped": "ALLOW_APIFY is not set"}, out["attempts"])

    def test_apify_runs_last_once_every_cheaper_route_failed_and_it_is_allowed(self):
        with self.fake({"apify_unblocker"}), mock.patch("fetchgate.creds.apify_token", return_value="tok"), \
                mock.patch.dict(os.environ, {"ALLOW_APIFY": "1"}):
            out = fetchgate.fetch(URL, creds_override={"PROXY_URL": RESI})
        self.assertEqual(self.calls, ["vm", "vm_camoufox", "residential", "residential_camoufox", "apify_unblocker"])
        self.assertEqual((out["route"], out["usd"]), ("apify_unblocker", round(70_000 / 1e9 + 70_000 / 1e9 + 0.0015, 6)))

    def test_apify_not_used_when_cheaper_routes_were_skipped(self):
        with self.fake(set()), mock.patch("fetchgate.creds.apify_token", return_value="tok"), \
                mock.patch.dict(os.environ, {"ALLOW_APIFY": "1"}):
            fetchgate.fetch(URL)  # no residential proxy: routes 3-4 never ran
            fetchgate.fetch(URL + "?2", creds_override={"PROXY_URL": RESI}, routes=("vm", "apify_unblocker"))
        self.assertNotIn("apify_unblocker", self.calls)

    def test_actor_runs_need_allow_apify(self):
        with mock.patch("fetchgate.creds.apify_token", return_value="tok"), mock.patch("requests.post") as post:
            with self.assertRaises(fetchgate.ApifyNotAllowed):
                fetchgate.run_actor("a~b", {})
        post.assert_not_called()

    def test_actor_cost_is_logged_from_apifys_report(self):
        started = mock.Mock(**{"json.return_value": {"data": {"id": "r1", "status": "RUNNING"}}})
        done = mock.Mock(**{"json.return_value": {"data": {"id": "r1", "status": "SUCCEEDED", "defaultDatasetId": "d",
                                                          "usageTotalUsd": 0.42}}})
        items = mock.Mock(**{"json.return_value": [{"x": 1}]})
        info: dict = {}
        with mock.patch("fetchgate.creds.apify_token", return_value="tok"), \
                mock.patch.dict(os.environ, {"ALLOW_APIFY": "1"}), mock.patch("requests.post", return_value=started), \
                mock.patch("requests.get", side_effect=[done, items]), mock.patch("time.sleep"):
            self.assertEqual(fetchgate.run_actor("a~b", {}, info=info), [{"x": 1}])
        self.assertEqual((info["usd"], self.rows()[-1]["route"], self.rows()[-1]["usd"]), (0.42, "apify_actor", 0.42))


class BudgetTest(GateCase):
    def spend(self, usd: float, job: str = "test-job"):
        L.ledger().record({"job": job, "route": "residential", "usd": usd, "ok": True})

    def test_budget_cap_stops_a_job_before_the_paid_attempt(self):
        self.spend(4.9999)
        with self.fake(set()):
            with self.assertRaises(fetchgate.BudgetExceeded):
                fetchgate.fetch(URL, creds_override={"PROXY_URL": RESI})
        self.assertEqual(self.calls, ["vm", "vm_camoufox"])  # free routes ran; the residential attempt never started

    def test_cap_defaults_to_5_and_only_the_env_var_raises_it(self):
        self.assertEqual((L.job_cap(), L.job_cap(100), L.job_cap(1)), (5.0, 5.0, 1.0))
        with mock.patch.dict(os.environ, {"FETCH_BUDGET_USD": "20"}):
            self.assertEqual(L.job_cap(100), 20.0)

    def test_new_job_names_do_not_escape_the_daily_cap(self):
        with mock.patch.dict(os.environ, {"FETCHGATE_DAILY_USD": "1"}):
            self.spend(0.9999, job="other")
            with self.fake(set()), self.assertRaises(fetchgate.BudgetExceeded):
                fetchgate.fetch(URL, job="brand-new", creds_override={"PROXY_URL": RESI})

    def test_totals_survive_a_restart(self):
        self.spend(1.25)
        L.set_ledger(L.Ledger(self.log))
        self.assertAlmostEqual(L.ledger().spent("test-job"), 1.25)

    def test_a_long_scroll_stops_when_it_would_pass_the_cap(self):
        self.spend(4.99)
        stops = []

        def load(url, proxy, **kw):
            stops.append(kw["stop"](2_000_000))  # 2 MB residential = $0.002: within the cap
            stops.append(kw["stop"](20_000_000))  # 20 MB = $0.02: past it
            return {"status": 200, "html": REAL[1], "final_url": url, "scrolls": 1, "responses": []}
        with mock.patch("fetchgate.browser.load", side_effect=load), \
                mock.patch.object(ladder, "ensure_tool", return_value={"ok": True}), \
                mock.patch.dict(os.environ, {"FETCH_BUDGET_USD": "5.0"}):
            ladder._BLOCKED[("producthunt.com", "vm_camoufox")] = __import__("time").time()
            with mock.patch.dict(gate.SCROLL_ESTIMATE_USD, {"residential_chromium": 0.001}):
                fetchgate.fetch("https://www.producthunt.com/@a/upvotes", scroll=True, creds_override={"PROXY_URL": RESI})
        self.assertEqual(stops, [False, True])


class ServiceTest(GateCase):
    def test_service_clamps_the_callers_budget_and_maps_errors(self):
        self.assertEqual(service._cap({"budget_usd": 1000}), 50.0)
        with mock.patch.dict(os.environ, {"FETCHGATE_MAX_JOB_USD": "10"}):
            self.assertEqual(service._cap({"budget_usd": 1000, "max_cost_usd": 3}), 3.0)
            self.assertEqual(service._cap({}), 5.0)
        self.spend_all()
        with self.fake(set()):
            code, body = service.handle("/fetch", {"url": URL, "job": "test-job", "creds": {"PROXY_URL": RESI}})
        self.assertEqual((code, body["kind"]), (402, "budget"))
        with mock.patch.dict(os.environ, {"FETCHGATE_APIFY": "0"}), self.fake(set()):
            code, body = service.handle("/actor", {"actor": "a~b", "allow_apify": True})
        self.assertEqual(code, 403)

    def spend_all(self):
        L.ledger().record({"job": "test-job", "route": "residential", "usd": 5.0, "ok": True})

    def test_health_reports_presence_never_values(self):
        with mock.patch("fetchgate.creds.residential", return_value=RESI):
            code, body = service.handle("/health", None)
        self.assertEqual((code, body["residential"]), (200, True))
        self.assertNotIn("u:p", json.dumps(body))

    def test_client_calls_the_service_over_http(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), service._Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with mock.patch.dict(os.environ, {"FETCHGATE_URL": f"http://127.0.0.1:{srv.server_port}"}), \
                    self.fake({"vm"}):
                out = fetchgate.fetch(URL)
                self.assertEqual((out["route"], out["job"]), ("vm", "test-job"))
                self.assertEqual(fetchgate.job_summary()["items_fetched"], 1)
                self.spend_all()
                with self.assertRaises(fetchgate.BudgetExceeded):  # free routes would still run; a paid one can't
                    fetchgate.fetch(URL + "?2", creds_override={"PROXY_URL": RESI}, routes=("residential",))
        finally:
            srv.shutdown()


class CredsTest(GateCase):
    def test_credentials_file_wins_and_redact_hides_them(self):
        from fetchgate import creds

        f = Path(self.tmp.name) / "credentials.env"
        f.write_text("RESIDENTIAL_PROXY_URL=http://a:b@gw.example.com:823\nAPIFY_TOKEN=apify_api_XYZ\n")
        with mock.patch.dict(os.environ, {"FETCHGATE_CREDENTIALS": str(f), "APIFY_TOKEN": "env-token"}):
            self.assertEqual(creds.residential(), "http://a:b@gw.example.com:823")
            self.assertEqual(creds.apify_token(), "apify_api_XYZ")
            self.assertEqual(creds.apify_token({"APIFY_TOKEN": "users-own"}), "users-own")
        self.assertEqual(creds.redact("x http://a:b@h:1 apify_api_XYZ ?token=abc"),
                         "x http://<redacted>@h:1 <redacted> ?token=<redacted>")


if __name__ == "__main__":
    unittest.main()
