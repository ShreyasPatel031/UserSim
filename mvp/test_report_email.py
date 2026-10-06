"""Report email links must be public https URLs, never localhost."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from mvp.report_email import build_message, report_base_url


class ReportBaseUrlTests(unittest.TestCase):
    def test_unset_defaults_to_prod(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(report_base_url(), "https://usersim.vercel.app")

    def test_loopback_and_http_fall_through_to_prod(self) -> None:
        cases = (
            "http://127.0.0.1:3000",
            "http://localhost:3000",
            "http://localhost",
            "http://example.com",
        )
        for value in cases:
            with mock.patch.dict(os.environ, {"MVP_PUBLIC_BASE_URL": value}, clear=True):
                self.assertEqual(report_base_url(), "https://usersim.vercel.app", value)

    def test_valid_https_origin_is_used(self) -> None:
        with mock.patch.dict(
            os.environ, {"MVP_PUBLIC_BASE_URL": "https://example.test/"}, clear=True
        ):
            self.assertEqual(report_base_url(), "https://example.test")

    def test_build_message_contains_prod_report_link(self) -> None:
        with mock.patch.dict(os.environ, {"GMAIL_USER": "sender@example.com"}, clear=True):
            study = SimpleNamespace(
                id="857bc1fa-e906-4d78-bac3-c7ebe6167fbb",
                url="https://aistudio.google.com/",
                summary={"headline": "short version"},
                email="reader@example.com",
            )
            msg = build_message(study, "reader@example.com")
            body = msg.get_content()
            self.assertIn(
                "https://usersim.vercel.app/report?study=857bc1fa-e906-4d78-bac3-c7ebe6167fbb",
                body,
            )
            self.assertNotIn("127.0.0.1", body)
            self.assertNotIn("localhost", body)


if __name__ == "__main__":
    unittest.main()
