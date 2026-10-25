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
        with mock.patch.object(F, "fetch", fake):
            out = F.probe("https://www.producthunt.com/products/linear/reviews", "http://user:secret@gw.example.com:823")
        self.assertEqual((out["chrome_fingerprint_via_proxy"]["status"], out["chrome_fingerprint_via_proxy"]["challenge"]), (200, False))
        self.assertTrue(out["chrome_fingerprint_direct"]["challenge"])
        self.assertNotIn("secret", str(out))


if __name__ == "__main__":
    unittest.main()
