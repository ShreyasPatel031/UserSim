"""Report email links must be public URLs, never localhost."""

from __future__ import annotations

import os
from types import SimpleNamespace

from mvp.report_email import build_message, report_base_url


def test_report_base_url_defaults_to_prod(monkeypatch):
    monkeypatch.delenv("MVP_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("MVP_REPORT_BASE_URL", raising=False)
    monkeypatch.delenv("VERCEL_URL", raising=False)
    assert report_base_url() == "https://usersim.vercel.app"


def test_report_base_url_respects_override(monkeypatch):
    monkeypatch.setenv("MVP_PUBLIC_BASE_URL", "https://example.test/")
    assert report_base_url() == "https://example.test"


def test_report_base_url_uses_vercel_url(monkeypatch):
    monkeypatch.delenv("MVP_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("MVP_REPORT_BASE_URL", raising=False)
    monkeypatch.setenv("VERCEL_URL", "usersim.vercel.app")
    assert report_base_url() == "https://usersim.vercel.app"


def test_build_message_contains_prod_report_link(monkeypatch):
    monkeypatch.delenv("MVP_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("MVP_REPORT_BASE_URL", raising=False)
    monkeypatch.delenv("VERCEL_URL", raising=False)
    monkeypatch.setenv("GMAIL_USER", "sender@example.com")
    study = SimpleNamespace(
        id="857bc1fa-e906-4d78-bac3-c7ebe6167fbb",
        url="https://aistudio.google.com/",
        summary={"headline": "short version"},
        email="reader@example.com",
    )
    msg = build_message(study, "reader@example.com")
    body = msg.get_content()
    assert "https://usersim.vercel.app/report?study=857bc1fa-e906-4d78-bac3-c7ebe6167fbb" in body
    assert "127.0.0.1" not in body
    assert "localhost" not in body
