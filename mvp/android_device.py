"""Android emulator (or phone) over a local Appium UiAutomator2 server, as a ``Device``.

Same interface as ``mvp.ios_agent.Device`` so ``run_goal`` and the study runner
work unchanged: screenshot + accessibility elements in, tap/type/swipe out.

    MVP_APPIUM_URL   Appium server (default http://127.0.0.1:4723)
    MVP_ANDROID_UDID emulator serial (default emulator-5554)
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET

from mvp.ios_agent import ELEMENT_CAP, Device, Element

_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
_EDIT = {"EditText", "AutoCompleteTextView", "MultiAutoCompleteTextView"}


def parse_android(source: str, scale: float, screen_w: int, screen_h: int) -> list[Element]:
    """Visible, labelled or clickable nodes; coordinates converted from pixels to tap units."""
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return []
    out: list[Element] = []
    seen: set[tuple] = set()
    for node in root.iter():
        if node.get("displayed", "true") != "true":
            continue
        cls = (node.get("class") or node.tag or "").rsplit(".", 1)[-1]
        label = (node.get("text") or node.get("content-desc") or node.get("hint") or "").strip()
        clickable = node.get("clickable") == "true"
        if cls in _EDIT:
            kind = "SecureTextField" if node.get("password") == "true" else "TextField"
            label = label or (node.get("resource-id") or "").rsplit("/", 1)[-1] or "text field"
        elif clickable:
            kind = "Button"
        elif label:
            kind = "StaticText"
        else:
            continue
        if not label and kind == "Button":
            continue
        m = _BOUNDS.search(node.get("bounds") or "")
        if not m:
            continue
        x1, y1, x2, y2 = (int(int(v) / scale) for v in m.groups())
        w, h = x2 - x1, y2 - y1
        if w <= 1 or h <= 1 or x1 >= screen_w or y1 >= screen_h:
            continue
        key = (kind, label, x1, y1)
        if key in seen:
            continue
        seen.add(key)
        out.append(Element(0, kind, label, x1, y1, w, h, node.get("enabled") != "false"))
    out.sort(key=lambda e: (e.y, e.x))
    for i, el in enumerate(out[:ELEMENT_CAP], 1):
        el.idx = i
    return out[:ELEMENT_CAP]


class AndroidDevice(Device):
    """``Device`` over UiAutomator2. Taps use window units (pixels / density scale)."""

    def __init__(self, *, session_name: str = "", build: str = "") -> None:  # noqa: D401
        from appium import webdriver
        from appium.options.android import UiAutomator2Options

        opts = UiAutomator2Options()
        opts.udid = os.environ.get("MVP_ANDROID_UDID", "emulator-5554")
        opts.no_reset = True
        opts.auto_grant_permissions = False
        opts.new_command_timeout = 600
        self.driver = webdriver.Remote(os.environ.get("MVP_APPIUM_URL", "http://127.0.0.1:4723"), options=opts)
        size = self.driver.get_window_size()
        self.w, self.h = int(size["width"]), int(size["height"])
        # page_source bounds are in physical pixels; taps/window size are not always.
        try:
            px_w = int(self.driver.execute_script("mobile: deviceInfo").get("realDisplaySize", "0x0").split("x")[0])
        except Exception:
            px_w = 0
        self.scale = (px_w / self.w) if px_w and self.w else 1.0

    def observe(self) -> tuple[bytes, list[Element], str]:
        png = self.driver.get_screenshot_as_png()
        source = self.driver.page_source
        return png, parse_android(source, self.scale, self.w, self.h), source

    def tap_xy(self, x: int, y: int) -> None:
        self.driver.execute_script("mobile: clickGesture", {"x": int(x * self.scale), "y": int(y * self.scale)})

    def type_text(self, text: str, submit: bool = False) -> None:
        try:
            self.driver.switch_to.active_element.send_keys(text)
        except Exception:
            self.driver.execute_script("mobile: type", {"text": text})
        if submit:
            self.driver.press_keycode(66)  # ENTER

    def fill_secure(self, text: str) -> None:
        from appium.webdriver.common.appiumby import AppiumBy

        fields = self.driver.find_elements(AppiumBy.XPATH, "//*[@password='true']")
        if fields:
            fields[0].click()
            fields[0].clear()
            fields[0].send_keys(text)
        else:
            self.type_text(text)

    def clear_focused(self) -> None:
        try:
            self.driver.switch_to.active_element.clear()
        except Exception:
            pass

    def swipe(self, direction: str) -> None:
        # "down" = scroll content down = finger moves up.
        w, h = self.w * self.scale, self.h * self.scale
        area = {"left": int(w * 0.1), "top": int(h * 0.2), "width": int(w * 0.8), "height": int(h * 0.6)}
        finger = {"down": "up", "up": "down", "left": "left", "right": "right"}.get(direction, "up")
        self.driver.execute_script("mobile: swipeGesture", {**area, "direction": finger, "percent": 0.7})

    def launch(self, bundle_id: str) -> None:
        self.driver.activate_app(bundle_id)

    def terminate(self, bundle_id: str) -> None:
        try:
            self.driver.terminate_app(bundle_id)
        except Exception:
            pass

    def remove(self, bundle_id: str) -> bool:
        """Clear app data (fresh first launch) without needing to reinstall from Play."""
        try:
            self.driver.execute_script("mobile: clearApp", {"appId": bundle_id})
            return True
        except Exception:
            return False

    def installed(self, bundle_id: str) -> bool:
        try:
            return bool(self.driver.is_app_installed(bundle_id))
        except Exception:
            return False

    def home(self) -> None:
        self.driver.press_keycode(3)

    def mark(self, passed: bool, reason: str) -> None:
        pass
