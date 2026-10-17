from unittest.mock import MagicMock

from mvp import ios_agent
from mvp.android_agent import Element

SOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<AppiumAUT>
  <XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App Store" visible="true" x="0" y="0" width="393" height="852">
    <XCUIElementTypeOther visible="true" x="0" y="0" width="393" height="852"/>
    <XCUIElementTypeButton name="Get" label="Get" visible="true" x="300" y="200" width="60" height="30"/>
    <XCUIElementTypeButton name="Hidden" label="Hidden" visible="false" x="0" y="0" width="60" height="30"/>
    <XCUIElementTypeSecureTextField name="Password" visible="true" x="20" y="400" width="350" height="44"/>
    <XCUIElementTypeStaticText label="Reframe: Drink Less" visible="true" x="20" y="100" width="200" height="20"/>
  </XCUIElementTypeApplication>
</AppiumAUT>"""


def test_parse_xcui_filters_and_centers():
    els = ios_agent.parse_xcui(SOURCE)
    assert [(e.cls, e.label) for e in els] == [
        ("Button", "Get"),
        ("SecureTextField", "Password"),
        ("StaticText", "Reframe: Drink Less"),
    ]
    assert els[0].center == (330, 215) and els[0].clickable
    assert els[1].editable


def test_parse_xcui_invalid():
    assert ios_agent.parse_xcui("<nope") == []


def test_execute_secret_and_open_app(monkeypatch):
    phone = MagicMock()
    monkeypatch.setenv("APPLE_ID_PASSWORD", "pw")
    step = {"action": "type_secret", "field": "apple_password"}
    assert ios_agent.execute(phone, step, [], (393, 852), {}, "b.id") == "ok"
    phone.type_text.assert_called_once_with("pw")
    assert ios_agent.execute(phone, {"action": "open_app", "app": "target"}, [], (393, 852), {}, "b.id") == "ok"
    phone.activate.assert_called_once_with("b.id")


def test_execute_tap_point_scales_to_points():
    phone = MagicMock()
    els = [Element(0, "Get", "Button", (330, 215), True, False)]
    assert ios_agent.execute(phone, {"action": "tap", "element": 0}, els, (393, 852), {}, "b") == "ok"
    phone.tap.assert_called_with(330, 215)
    ios_agent.execute(phone, {"action": "tap_point", "point": [500, 500]}, els, (400, 800), {}, "b")
    phone.tap.assert_called_with(200, 400)


def test_capabilities_use_env(monkeypatch):
    monkeypatch.setenv("BROWSERSTACK_USERNAME", "u")
    monkeypatch.setenv("BROWSERSTACK_ACCESS_KEY", "k")
    caps = ios_agent.capabilities("t", "iPhone 15", "17", "bs://x")
    assert caps["appium:app"] == "bs://x"
    assert caps["bstack:options"]["userName"] == "u" and caps["bstack:options"]["deviceName"] == "iPhone 15"
