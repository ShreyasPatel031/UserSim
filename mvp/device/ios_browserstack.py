"""iPhone backend on BrowserStack App Automate (Appium/XCUITest).

Exposes the same observe/act shape as the MCP browser session tools so it can be
plugged into mvp/sim_mcp as a device backend:

  observe() -> {"screenshot_png": bytes, "elements": [...], "size": {w,h}}
  act({"action": "tap", "x":..,"y":..}) | type(text) | swipe(dir) | home | launch(bundle)

Credentials come from env (BROWSERSTACK_USERNAME / BROWSERSTACK_ACCESS_KEY);
nothing is logged. App Store installs follow BrowserStack's documented flow:
start a session on any uploaded app, open com.apple.AppStore, sign in, install,
then activate the installed bundle id.
"""
from __future__ import annotations

import base64
import os
import re
import xml.etree.ElementTree as ET
from typing import Any

from appium import webdriver
from appium.options.ios import XCUITestOptions

HUB = "https://hub-cloud.browserstack.com/wd/hub"


class IOSDevice:
    def __init__(self, app: str, device: str = "iPhone 15", os_version: str = "17",
                 name: str = "usersim-ios"):
        opts = XCUITestOptions()
        opts.platform_name = "ios"
        opts.set_capability("appium:app", app)
        opts.set_capability("bstack:options", {
            "userName": os.environ["BROWSERSTACK_USERNAME"],
            "accessKey": os.environ["BROWSERSTACK_ACCESS_KEY"],
            "deviceName": device, "osVersion": os_version,
            "projectName": "UserSim", "buildName": "ios-device-backend",
            "sessionName": name, "idleTimeout": 300,
            "appiumVersion": "2.12.1", "interactiveDebugging": True,
        })
        opts.set_capability("appium:newCommandTimeout", 600)
        opts.set_capability("appium:autoAcceptAlerts", False)
        self.d = webdriver.Remote(HUB, options=opts)
        self.size = self.d.get_window_size()

    # ---- observe -------------------------------------------------------
    def elements(self, limit: int = 120) -> list[dict[str, Any]]:
        out = []
        try:
            root = ET.fromstring(self.d.page_source.encode())
        except Exception:
            return out
        for e in root.iter():
            a = e.attrib
            if a.get("visible") != "true":
                continue
            label = a.get("label") or a.get("name") or a.get("value") or ""
            t = e.tag.replace("XCUIElementType", "")
            if not label and t not in ("TextField", "SecureTextField", "Button"):
                continue
            try:
                x, y, w, h = (int(a.get(k, 0)) for k in ("x", "y", "width", "height"))
            except ValueError:
                continue
            if w <= 0 or h <= 0:
                continue
            out.append({"type": t, "label": label[:80], "x": x + w // 2, "y": y + h // 2})
            if len(out) >= limit:
                break
        return out

    def observe(self) -> dict[str, Any]:
        png = base64.b64decode(self.d.get_screenshot_as_base64())
        return {"screenshot_png": png, "elements": self.elements(), "size": self.size}

    # ---- act -----------------------------------------------------------
    def act(self, a: dict[str, Any]) -> str:
        k = a["action"]
        if k == "tap":
            self.d.execute_script("mobile: tap", {"x": a["x"], "y": a["y"]})
        elif k == "tap_label":
            el = self.d.find_element("-ios predicate string",
                                     f'label == "{a["label"]}" OR name == "{a["label"]}"')
            el.click()
        elif k == "type":
            self.d.switch_to.active_element.send_keys(a["text"])
        elif k == "swipe":
            self.d.execute_script("mobile: swipe", {"direction": a.get("direction", "up")})
        elif k == "home":
            self.d.execute_script("mobile: pressButton", {"name": "home"})
        elif k == "launch":
            self.d.execute_script("mobile: launchApp", {"bundleId": a["bundle"]})
        elif k == "activate":
            self.d.activate_app(a["bundle"])
        elif k == "wait":
            import time; time.sleep(float(a.get("s", 2)))
        else:
            raise ValueError(k)
        return "ok"

    def quit(self):
        try:
            self.d.quit()
        except Exception:
            pass
