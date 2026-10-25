"""In-house review page probe: allowed hosts only, challenge detection, proxy credentials never echoed."""

from __future__ import annotations

import unittest
from unittest import mock

from mvp import review_fetch as F


class ReviewFetchTest(unittest.TestCase):
    def test_only_https_review_sites(self):
        self.assertTrue(F.allowed("https://www.g2.com/products/linear/reviews"))
        self.assertTrue(F.allowed("https://www.producthunt.com/products/linear/reviews"))
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
        self.assertEqual(F.sticky_proxy("http://u:p@gw.dataimpulse.com:823", 3), "http://u__cr.us:p@gw.dataimpulse.com:10003")
        self.assertEqual(F.sticky_proxy("http://u__cr.us:p@gw.dataimpulse.com:823", 1), "http://u__cr.us:p@gw.dataimpulse.com:10001")
        self.assertEqual(F._capsolver_proxy("http://u:p@gw.dataimpulse.com:10001"), "gw.dataimpulse.com:10001:u:p")
        self.assertEqual(F._cookie_header({"cookies": {"cf_clearance": "x"}}), "cf_clearance=x")
        self.assertEqual(F._cookie_header({"cookie": "datadome=abc; Max-Age=31536000; Domain=.g2.com"}), "datadome=abc")


if __name__ == "__main__":
    unittest.main()
