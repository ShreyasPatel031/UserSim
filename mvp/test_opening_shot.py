from __future__ import annotations

import base64
from pathlib import Path

from mvp.opening_shot import drop_inline_shots, drop_inline_shots_inplace, png_data_url, strip_live_view


def test_png_data_url_roundtrip(tmp_path: Path) -> None:
    png = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00" * 120
    )
    path = tmp_path / "bbox_0.png"
    path.write_bytes(png)
    url = png_data_url(path)
    assert url and url.startswith("data:image/png;base64,")
    raw = base64.b64decode(url.split(",", 1)[1])
    assert raw == png


def test_png_data_url_rejects_tiny(tmp_path: Path) -> None:
    path = tmp_path / "tiny.png"
    path.write_bytes(b"nope")
    assert png_data_url(path) is None


def test_drop_inline_and_live_view() -> None:
    payload = {
        "live_sessions": [
            {
                "agent_id": "t1",
                "live_view_url": "https://www.browserbase.com/devtools-fullscreen/x",
                "trace": [
                    {
                        "step": 0,
                        "screenshot_url": "/api/x.png",
                        "screenshot_data_url": "data:image/png;base64,AAAA",
                    }
                ],
            }
        ]
    }
    cleaned = drop_inline_shots(payload)
    assert "screenshot_data_url" not in cleaned["live_sessions"][0]["trace"][0]
    assert cleaned["live_sessions"][0]["trace"][0]["screenshot_url"] == "/api/x.png"
    # live view is kept for agent-start UI (screenshot still primary until live_active).
    kept = strip_live_view(dict(payload["live_sessions"][0]))
    assert kept.get("live_view_url")
    drop_inline_shots_inplace(payload)
    assert "screenshot_data_url" not in payload["live_sessions"][0]["trace"][0]


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        test_png_data_url_roundtrip(Path(td))
        test_png_data_url_rejects_tiny(Path(td))
    test_drop_inline_and_live_view()
    print("ok")


import unittest


class FinalPngAndClocksTest(unittest.TestCase):
    def test_png_bytes_require_magic_and_size(self) -> None:
        from mvp.opening_shot import png_bytes_ok

        self.assertFalse(png_bytes_ok(None))
        self.assertFalse(png_bytes_ok(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100))
        self.assertTrue(png_bytes_ok(b"\x89PNG\r\n\x1a\n" + b"\x00" * 2100))

    def test_publish_final_png_rejects_an_empty_id(self) -> None:
        from mvp.opening_shot import publish_final_png

        self.assertEqual(publish_final_png("", "agent"), "")
        self.assertEqual(publish_final_png("study", ""), "")

    def test_headline_clocks_use_url_submit_and_report_ready(self) -> None:
        from mvp.study import headline_clocks

        clocks = headline_clocks(
            url_submit_at_ts=1_000.0,
            report_ready_at_ts=1_061.5,
            runs=[{"agent_id": "t1__p1__product", "first_action_at_ts": 1_003.2}],
            complete=True,
        )
        self.assertEqual(clocks["time_to_first_value_s"], 3.2)
        self.assertEqual(clocks["time_to_first_value_agent"], "t1__p1__product")
        self.assertEqual(clocks["total_time_s"], 61.5)
        self.assertTrue(clocks["report_ready"])
        incomplete = headline_clocks(
            url_submit_at_ts=1_000.0,
            report_ready_at_ts=None,
            runs=[{"agent_id": "t1", "first_action_at_ts": 1_004.0}],
            complete=False,
        )
        self.assertIsNone(incomplete["total_time_s"])
        self.assertFalse(incomplete["report_ready"])

    def test_page_open_and_first_action_must_differ(self) -> None:
        from mvp.a11y_agent import should_replace_open

        self.assertTrue(should_replace_open(started=10.0, now=14.0, opened=None))
        self.assertTrue(should_replace_open(started=10.0, now=11.0, opened=10.0))
        self.assertTrue(should_replace_open(started=10.0, now=14.0, opened=14.0))
        self.assertFalse(should_replace_open(started=10.0, now=11.0, opened=10.4))
