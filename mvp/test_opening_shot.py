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
    stripped = strip_live_view(dict(payload["live_sessions"][0]))
    assert "live_view_url" not in stripped
    drop_inline_shots_inplace(payload)
    assert "screenshot_data_url" not in payload["live_sessions"][0]["trace"][0]


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        test_png_data_url_roundtrip(Path(td))
        test_png_data_url_rejects_tiny(Path(td))
    test_drop_inline_and_live_view()
    print("ok")
