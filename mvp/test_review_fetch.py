"""In-house review page probe: allowed hosts only, challenge detection, proxy credentials never echoed."""

from __future__ import annotations

import unittest
from unittest import mock

from mvp import review_fetch as F


class ReviewFetchTest(unittest.TestCase):
    def test_only_https_review_sites(self):
        self.assertTrue(F.allowed("https://www.g2.com/products/linear/reviews"))
        self.assertTrue(F.allowed("https://www.producthunt.com/products/linear/reviews"))
        self.assertTrue(F.allowed("https://x.com/levelsio/followers"))
        self.assertFalse(F.allowed("https://evilx.com/"))
        self.assertFalse(F.allowed("http://www.g2.com/products/linear/reviews"))
        self.assertFalse(F.allowed("https://evil.com/?u=g2.com"))
        self.assertFalse(F.allowed("https://g2.com.evil.com/"))
        with self.assertRaises(ValueError):
            F.probe("https://example.com/", None)

    def test_challenge_detected_and_proxy_password_redacted(self):
        def fake(url, proxy, impersonate="chrome", timeout=45.0):
            if proxy and impersonate:
                return 200, "<title>Linear Reviews 2026</title>" + "x" * 30000
            if proxy:
                raise RuntimeError("Failed to connect via http://user:secret@gw.example.com:823")
            return 403, "<title>Just a moment...</title>"
        with mock.patch.object(F, "fetch", fake), mock.patch.object(F, "ensure_browser", return_value={"ok": False}), \
                mock.patch.object(F, "ensure_tool", return_value={"ok": False}), \
                mock.patch.object(F, "exit_country", return_value={"country": "US"}), \
                mock.patch.object(F, "rotation", return_value={}):
            out = F.probe("https://www.producthunt.com/products/linear/reviews", "http://user:secret@gw.example.com:823")
        self.assertEqual((out["chrome_fingerprint_via_proxy"]["status"], out["chrome_fingerprint_via_proxy"]["challenge"]), (200, False))
        self.assertTrue(out["chrome_fingerprint_direct"]["challenge"])
        self.assertNotIn("secret", str(out))
        self.assertTrue(F._summary(200, "<title>Un instant…</title>" + "x" * 30000, 0)["challenge"])

    def test_rotation_stops_at_first_ip_that_gets_through(self):
        calls = iter([(403, "<title>Just a moment...</title>"), (200, "<title>Shortcut Reviews</title>" + "x" * 30000)])
        with mock.patch.object(F, "fetch", lambda *a, **k: next(calls)):
            out = F.rotation("https://www.capterra.com/p/1/X/reviews/", "http://u:p@gw.example.com:823")
        self.assertEqual((out["attempts"], out["passed_on_attempt"], out["statuses"]), (2, 2, [403, 200]))

    def test_apify_proxy_urls_and_cert_relaxation_only_for_unblocker(self):
        resp = mock.Mock()
        resp.json.return_value = {"data": {"proxy": {"password": "pw"}}}
        with mock.patch("mvp.discovery.apify_token", return_value="tok"), mock.patch("requests.get", return_value=resp):
            self.assertEqual(F.apify_proxy("UNBLOCKER"), "http://groups-UNBLOCKER:pw@proxy.apify.com:8000")
            self.assertEqual(F.apify_proxy("RESIDENTIAL"), "http://groups-RESIDENTIAL,country-US:pw@proxy.apify.com:8000")
        self.assertTrue(F._intercepting("http://groups-UNBLOCKER:pw@proxy.apify.com:8000"))
        self.assertFalse(F._intercepting("http://u:p@gw.dataimpulse.com:823"))

    def test_own_unblocker_helpers(self):
        dns = ("gw.dataimpulse.com", [], ["64.34.81.89", "64.34.81.65"])
        with mock.patch("socket.gethostbyname_ex", return_value=dns):  # pinned to one IP: CapSolver rejects round-robin DNS
            self.assertEqual(F.sticky_proxy("http://u:p@gw.dataimpulse.com:823", 3), "http://u__cr.us:p@64.34.81.65:10003")
            self.assertEqual(F.sticky_proxy("http://u__cr.us:p@gw.dataimpulse.com:823", 1), "http://u__cr.us:p@64.34.81.65:10001")
        with mock.patch("socket.gethostbyname_ex", side_effect=OSError):
            self.assertEqual(F.sticky_proxy("http://u:p@gw.dataimpulse.com:823", 2), "http://u__cr.us:p@gw.dataimpulse.com:10002")
        with mock.patch("socket.gethostbyname", return_value="1.2.3.4"):
            self.assertEqual(F._capsolver_proxy("http://u:p@gw.dataimpulse.com:10001"), "1.2.3.4:10001:u:p")
        self.assertEqual(F._cookie_header({"cookies": {"cf_clearance": "x"}}), "cf_clearance=x")
        self.assertEqual(F._cookie_header({"cookie": "datadome=abc; Max-Age=31536000; Domain=.g2.com"}), "datadome=abc")


class LadderTest(unittest.TestCase):
    REAL = (200, "<title>Reviews</title>" + "x" * 30000)
    WALL = (403, "<title>Just a moment...</title>")

    def setUp(self):
        F._BLOCKED.clear()

    def test_cheapest_route_that_passes_and_blocked_routes_are_skipped_next_time(self):
        calls = []

        def fake(tier, url, residential, meter=None):
            calls.append(tier)
            if meter is not None:
                meter["bytes"] = 70_000
            return self.REAL if tier == "residential" else self.WALL
        with mock.patch.object(F, "tier_fetch", side_effect=fake):
            status, _, route, tried = F.ladder_fetch("https://www.capterra.com/p/1/X/reviews/", "http://u:p@gw:823")
            self.assertEqual((status, route, calls), (200, "residential", ["vm", "vm_camoufox", "residential"]))
            self.assertAlmostEqual(tried[-1]["usd"], 0.00007)
            calls.clear()
            F.ladder_fetch("https://www.capterra.com/p/1/X/reviews/?page=2", "http://u:p@gw:823")
            self.assertEqual(calls, ["residential"])  # VM routes hit a wall on this site a moment ago
            calls.clear()
            F.ladder_fetch("https://www.g2.com/products/x/reviews", None)  # other site; no residential proxy saved
            self.assertEqual(calls, ["vm", "vm_camoufox", "apify_unblocker"])

    def test_errors_and_timeouts_fall_through_without_blocking_the_route(self):
        def fake(tier, url, residential, meter=None):
            if tier == "vm":
                raise TimeoutError("slow")
            return self.REAL
        with mock.patch.object(F, "tier_fetch", side_effect=fake):
            self.assertEqual(F.ladder_fetch("https://www.trustradius.com/products/x/reviews", None)[2], "vm_camoufox")
        self.assertNotIn(("trustradius.com", "vm"), F._BLOCKED)

    def test_localised_and_mid_size_challenge_pages_are_not_passes(self):
        cf = "<title>Трохи зачекайте…</title>" + "<script src='/cdn-cgi/challenge-platform/x'></script>" + "x" * 28000
        self.assertFalse(F.is_clean(200, cf))
        self.assertFalse(F.is_clean(200, "<title>Один момент…</title>" + "x" * 28000))
        self.assertTrue(F.is_clean(200, "<title>Asana Reviews</title><script>datadome</script>" + "x" * 300_000))

    def test_residential_is_pinned_to_us_exits(self):
        self.assertEqual(F.us_exit("http://u:p@gw.dataimpulse.com:823"), "http://u__cr.us:p@gw.dataimpulse.com:823")
        self.assertEqual(F.us_exit("http://u__cr.de:p@gw.dataimpulse.com:823"), "http://u__cr.de:p@gw.dataimpulse.com:823")
        self.assertEqual(F.us_exit("http://u:p@other.example:8000"), "http://u:p@other.example:8000")

    def test_costs(self):
        self.assertEqual(F.tier_cost("vm_camoufox", 10**6), 0.0)
        self.assertAlmostEqual(F.tier_cost("residential_camoufox", 2 * 10**6), 0.002)
        self.assertEqual(F.tier_cost("apify_unblocker", 0), F.UNBLOCKER_USD_PER_PAGE)
        self.assertEqual(F.tier_cost("apify_unblocker", 0, ok=False), 0.0)  # failed Unblocker requests aren't billed


if __name__ == "__main__":
    unittest.main()
