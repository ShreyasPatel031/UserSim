from __future__ import annotations

import base64
from pathlib import Path

import unittest
from datetime import datetime, timedelta, timezone

from mvp.opening_shot import (
    drop_inline_shots,
    drop_inline_shots_inplace,
    png_bytes_ok,
    png_data_url,
    publish_final_png,
    strip_live_view,
)
from mvp.study import headline_clocks


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


class FinalPngAndClocksTest(unittest.TestCase):
    def test_short_or_non_png_is_not_a_final(self) -> None:
        self.assertFalse(png_bytes_ok(None))
        self.assertFalse(png_bytes_ok(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20))
        self.assertTrue(png_bytes_ok(b"\x89PNG\r\n\x1a\n" + b"\x00" * 2100))

    def test_missing_ids_do_not_invent_a_url(self) -> None:
        self.assertEqual(publish_final_png("", "t1__p1__product"), "")
        self.assertEqual(publish_final_png("study", ""), "")

    def test_headline_clocks_use_url_submit_not_a_later_poll(self) -> None:
        submit = datetime(2026, 9, 26, tzinfo=timezone.utc)
        acted = (submit + timedelta(seconds=3.2)).timestamp()
        clocks = headline_clocks(
            created_at=submit.isoformat(),
            updated_at=(submit + timedelta(seconds=61.5)).isoformat(),
            runs=[
                {"agent_id": "t1__p1__product", "first_action_at_ts": acted},
                {
                    "agent_id": "t2__p1__product",
                    "first_action_at_ts": (submit + timedelta(seconds=9)).timestamp(),
                },
            ],
            complete=True,
        )
        self.assertEqual(clocks["time_to_first_value_s"], 3.2)
        self.assertEqual(clocks["time_to_first_value_agent"], "t1__p1__product")
        self.assertEqual(clocks["total_time_s"], 61.5)
        self.assertTrue(clocks["report_ready"])
        open_study = headline_clocks(
            created_at=submit.isoformat(),
            updated_at=(submit + timedelta(seconds=4)).isoformat(),
            runs=[{"agent_id": "t1__p1__product", "first_action_at_ts": acted}],
            complete=False,
        )
        self.assertEqual(open_study["time_to_first_value_s"], 3.2)
        self.assertIsNone(open_study["total_time_s"])
        self.assertFalse(open_study["report_ready"])


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        test_png_data_url_roundtrip(Path(td))
        test_png_data_url_rejects_tiny(Path(td))
    test_drop_inline_and_live_view()
    print("ok")
