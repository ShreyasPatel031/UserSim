"""Real-device sessions (mvp/sim_mcp/devices.py): parsing and guards, no network."""
from unittest import mock

import pytest

from mvp.sim_mcp import devices as D

SRC = """<hierarchy><android.widget.FrameLayout bounds="[0,0][1080,2340]">
<android.widget.Button text="COLOR" clickable="true" bounds="[96,795][516,915]"/>
<android.widget.EditText text="" clickable="true" bounds="[40,300][840,400]"/>
<android.view.View bounds="[0,0][10,10]"/></android.widget.FrameLayout></hierarchy>"""


def test_elements_from_android_source():
    d = D.DeviceSession(id="x", owner="o", app="lt://APP12345678", platform="android", task="t", persona="p", wd="w")
    with mock.patch.object(D.DeviceSession, "_call", return_value=SRC):
        els = d.elements()
    assert {"kind": "Button", "label": "COLOR", "x": 306, "y": 855} in els
    assert any(e.get("input") for e in els)
    assert len(els) == 2


def test_resolve_app_rejects_bad_input():
    with pytest.raises(D.DeviceError):
        D.resolve_app("ftp://x/app.apk")
    assert D.resolve_app("lt://APP1016032164179554") == "lt://APP1016032164179554"


def test_upload_file_rejects_non_zip(monkeypatch):
    monkeypatch.setenv("LT_USERNAME", "u")
    monkeypatch.setenv("LT_ACCESS_KEY", "k")
    with pytest.raises(D.DeviceError):
        D.upload_file(b"hello", "a.apk")


def test_no_credentials_message(monkeypatch):
    monkeypatch.delenv("LT_USERNAME", raising=False)
    monkeypatch.delenv("LT_ACCESS_KEY", raising=False)
    with pytest.raises(D.DeviceError, match="not configured"):
        D.creds()
