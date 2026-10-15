"""BrowserStack App Live as a ``Device`` for ``mvp.ios_agent.run_goal``.

App Live has no automation API: it streams a real iPhone into a web page.
This drives that page with Playwright the way a person would. Each step is a
screenshot of the whole page (dashboard + phone stream); the model clicks by
page coordinates, types through the keyboard, and the DOM controls of the
dashboard are offered as numbered elements to make navigation reliable.

Web login comes from the vault entry matching ``browserstack.com``
(``username`` / ``password``); the signed-in browser profile is kept in
``secrets/browserstack_profile`` so later runs skip login.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from mvp.credentials import credentials_for_url
from mvp.ios_agent import ROOT, Element

PROFILE = ROOT / "secrets" / "browserstack_profile"
DASHBOARD = "https://app-live.browserstack.com/"
VIEW_W, VIEW_H = 1440, 900

_DOM_ELEMENTS_JS = """
() => {
  const sel = 'button,a,input,select,textarea,[role=button],[role=option],[role=tab],[role=menuitem],li[class*=device],div[class*=device]';
  const out = [];
  for (const e of document.querySelectorAll(sel)) {
    const r = e.getBoundingClientRect();
    if (r.width < 4 || r.height < 4 || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
    const st = getComputedStyle(e);
    if (st.visibility === 'hidden' || st.display === 'none' || +st.opacity === 0) continue;
    const val = (e.type === 'password') ? '' : (e.value || '');
    let label = (e.getAttribute('aria-label') || e.innerText || val || e.placeholder || e.title || e.alt || '').trim().replace(/\\s+/g, ' ');
    if (!label) continue;
    out.push({kind: e.tagName === 'INPUT' ? (e.type === 'password' ? 'SecureTextField' : 'TextField') : 'Button',
              label: label.slice(0, 80), x: Math.round(r.left), y: Math.round(r.top),
              w: Math.round(r.width), h: Math.round(r.height), enabled: !e.disabled});
  }
  return out.slice(0, 120);
}
"""


class AppLiveDevice:
    """Duck-types ``mvp.ios_agent.Device`` over the App Live web UI."""

    def __init__(self, *, session_name: str = "", build: str = "", headless: bool = True) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        PROFILE.mkdir(parents=True, exist_ok=True)
        launch: dict[str, Any] = {
            "headless": headless,
            "viewport": {"width": VIEW_W, "height": VIEW_H},
            "args": ["--no-sandbox", "--use-fake-ui-for-media-stream"],
        }
        exe = Path("/opt/pw-browsers/chromium")
        if exe.exists():
            launch["executable_path"] = str(exe)
        self.ctx = self._pw.chromium.launch_persistent_context(str(PROFILE), **launch)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.w, self.h = VIEW_W, VIEW_H
        self.stream_only = True  # phone UI is pixels only; no accessibility tree
        self.session_id = f"applive-{int(time.time())}"
        self.page.goto(DASHBOARD, wait_until="domcontentloaded", timeout=90000)
        self.page.wait_for_timeout(4000)
        self._login_if_needed()

    # -- login ---------------------------------------------------------------
    def _login_if_needed(self) -> None:
        page = self.page
        if "sign_in" not in page.url and not page.locator('input[name="user[login]"]').count():
            return
        import os

        creds = credentials_for_url("https://www.browserstack.com") or {
            "username": os.environ.get("BROWSERSTACK_WEB_EMAIL", ""),
            "password": os.environ.get("BROWSERSTACK_WEB_PASSWORD", ""),
        }
        if not creds.get("username") or not creds.get("password"):
            raise RuntimeError("BrowserStack web login missing: set BROWSERSTACK_WEB_EMAIL / BROWSERSTACK_WEB_PASSWORD "
                               "or a vault site matching browserstack.com")
        page.fill('input[name="user[login]"]', creds["username"])
        page.fill('input[name="user[password]"]', creds["password"])
        page.click('input[name="commit"]')
        try:
            page.wait_for_url(lambda u: "sign_in" not in u, timeout=45000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        if "sign_in" not in page.url and "app-live" not in page.url:
            page.goto(DASHBOARD, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(4000)

    # -- Device interface ----------------------------------------------------
    def observe(self) -> tuple[bytes, list[Element], str]:
        png = self.page.screenshot()
        try:
            raw = self.page.evaluate(_DOM_ELEMENTS_JS)
        except Exception:
            raw = []
        els = [Element(0, r["kind"], r["label"], r["x"], r["y"], r["w"], r["h"], r["enabled"]) for r in raw]
        els.sort(key=lambda e: (e.y, e.x))
        for i, el in enumerate(els, 1):
            el.idx = i
        return png, els, ""

    def tap_xy(self, x: int, y: int) -> None:
        self.page.mouse.click(x, y)

    def type_text(self, text: str, submit: bool = False) -> None:
        self.page.keyboard.type(text, delay=70)
        if submit:
            self.page.keyboard.press("Enter")

    def fill_secure(self, text: str) -> None:
        self.type_text(text)

    def clear_focused(self) -> None:
        pass

    def _stream_box(self) -> dict | None:
        for sel in ("canvas", "video"):
            loc = self.page.locator(sel)
            best = None
            for i in range(loc.count()):
                box = loc.nth(i).bounding_box()
                if box and (best is None or box["width"] * box["height"] > best["width"] * best["height"]):
                    best = box
            if best and best["height"] > 200:
                return best
        return None

    def swipe(self, direction: str) -> None:
        box = self._stream_box() or {"x": self.w * 0.35, "y": self.h * 0.1, "width": self.w * 0.3, "height": self.h * 0.8}
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        dy = box["height"] * 0.3
        dx = box["width"] * 0.3
        start, end = {
            "down": ((cx, cy + dy), (cx, cy - dy)),
            "up": ((cx, cy - dy), (cx, cy + dy)),
            "left": ((cx + dx, cy), (cx - dx, cy)),
            "right": ((cx - dx, cy), (cx + dx, cy)),
        }.get(direction, ((cx, cy + dy), (cx, cy - dy)))
        self.page.mouse.move(*start)
        self.page.mouse.down()
        steps = 12
        for k in range(1, steps + 1):
            self.page.mouse.move(start[0] + (end[0] - start[0]) * k / steps, start[1] + (end[1] - start[1]) * k / steps)
            time.sleep(0.02)
        self.page.mouse.up()

    # App Live exposes no app-management API; the model does these on screen.
    def launch(self, bundle_id: str) -> None:
        pass

    def terminate(self, bundle_id: str) -> None:
        pass

    def remove(self, bundle_id: str) -> bool:
        return False

    def installed(self, bundle_id: str) -> bool:
        return False

    def home(self) -> None:
        pass

    def mark(self, passed: bool, reason: str) -> None:
        pass

    def screenshot(self) -> bytes:
        return self.page.screenshot()

    def end_session(self) -> None:
        """Leave the live session so the device is released and wiped."""
        try:
            self.page.goto(DASHBOARD, wait_until="domcontentloaded", timeout=60000)
            self.page.wait_for_timeout(3000)
        except Exception:
            pass

    def quit(self) -> None:
        try:
            self.ctx.close()
        finally:
            self._pw.stop()
