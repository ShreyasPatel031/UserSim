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

    def __init__(self, *, session_name: str = "", build: str = "", headless: bool | None = None) -> None:
        import os

        from playwright.sync_api import sync_playwright

        if headless is None:
            # Headed Chrome (under Xvfb on servers) attaches the WebRTC stream more reliably.
            headless = not os.environ.get("DISPLAY") or os.environ.get("MVP_APPLIVE_HEADLESS") == "1"

        self._pw = sync_playwright().start()
        PROFILE.mkdir(parents=True, exist_ok=True)
        launch: dict[str, Any] = {
            "headless": headless,
            "viewport": {"width": VIEW_W, "height": VIEW_H},
            "args": ["--no-sandbox", "--use-fake-ui-for-media-stream"],
        }
        # The device stream is H.264, which Playwright's bundled Chromium cannot decode
        # (the phone sits on a boot screen forever). Prefer real Google Chrome.
        for exe in ("/usr/bin/google-chrome", "/opt/google/chrome/chrome", "/opt/pw-browsers/chromium"):
            if Path(exe).exists():
                launch["executable_path"] = exe
                break
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
        """Screenshot + dashboard controls.

        Once the phone is streaming, the image is cropped to the phone (pointing is far
        more accurate on a phone-sized image) and all coordinates, element boxes
        included, are relative to that crop; ``tap_xy`` adds the offset back.
        """
        box = self._stream_box()
        if box and box["height"] > 300:
            pad = 6
            self._off = (max(int(box["x"]) - pad, 0), max(int(box["y"]) - pad, 0))
            clip = {"x": self._off[0], "y": self._off[1],
                    "width": min(int(box["width"]) + 2 * pad, VIEW_W - self._off[0]),
                    "height": min(int(box["height"]) + 2 * pad, VIEW_H - self._off[1])}
            png = self.page.screenshot(clip=clip)
            self.w, self.h = clip["width"], clip["height"]
        else:
            self._off = (0, 0)
            png = self.page.screenshot()
            self.w, self.h = VIEW_W, VIEW_H
        try:
            raw = self.page.evaluate(_DOM_ELEMENTS_JS)
        except Exception:
            raw = []
        ox, oy = self._off
        els = [Element(0, r["kind"], r["label"], r["x"] - ox, r["y"] - oy, r["w"], r["h"], r["enabled"]) for r in raw]
        els.sort(key=lambda e: (e.y, e.x))
        for i, el in enumerate(els, 1):
            el.idx = i
        return png, els, ""

    def tap_xy(self, x: int, y: int) -> None:
        ox, oy = getattr(self, "_off", (0, 0))
        self.page.mouse.click(x + ox, y + oy)

    def type_text(self, text: str, submit: bool = False) -> None:
        self.page.keyboard.type(text, delay=70)
        if submit:
            self.page.keyboard.press("Enter")

    def fill_secure(self, text: str) -> None:
        self.type_text(text)

    def clear_focused(self) -> None:
        pass

    def _stream_box(self) -> dict | None:
        """Visible box of the phone stream: the tall video/canvas with the most on-screen area."""
        try:
            return self.page.evaluate(
                """() => {
                  let best = null, bestArea = 0;
                  for (const e of document.querySelectorAll('video,canvas')) {
                    const r = e.getBoundingClientRect();
                    const x0 = Math.max(r.left, 0), y0 = Math.max(r.top, 0);
                    const x1 = Math.min(r.right, innerWidth), y1 = Math.min(r.bottom, innerHeight);
                    const w = x1 - x0, h = y1 - y0;
                    if (w < 150 || h < 300 || h < w) continue;
                    if (w * h > bestArea) { bestArea = w * h; best = {x: x0, y: y0, width: w, height: h}; }
                  }
                  return best;
                }"""
            )
        except Exception:
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

    def start_session(self, device: str = "iPhone 15", timeout_s: float = 300.0) -> bool:
        """Start an iOS session via 'Install via App Store' (boots straight into the App Store).

        Deterministic clicks, then wait until the phone video is actually playing.
        """
        page = self.page
        page.goto(DASHBOARD, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(5000)
        for text in ("Got it", "Close promotional notification"):
            try:
                page.get_by_text(text, exact=True).first.click(timeout=2000)
            except Exception:
                pass
        page.get_by_text("Install via App Store", exact=False).first.click(timeout=15000)
        page.wait_for_timeout(2000)
        try:
            page.get_by_text("REAL DEVICES").nth(1).click(timeout=5000)  # iOS tab
        except Exception:
            pass
        page.wait_for_timeout(1500)
        page.get_by_text(device, exact=True).first.click(timeout=15000)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            page.wait_for_timeout(5000)
            playing = page.evaluate(
                "() => Array.from(document.querySelectorAll('video')).some(v => v.readyState >= 3 && v.videoWidth > 100 && !v.paused)"
            )
            if playing:
                page.wait_for_timeout(8000)
                return True
        return False

    def reload(self) -> None:
        """Reload the App Live page; re-attaches a stream stuck on the boot screen."""
        self.page.reload(wait_until="domcontentloaded", timeout=90000)
        self.page.wait_for_timeout(8000)

    def end_session(self) -> None:
        """Stop the live session (frees the plan's single parallel slot), then go to the dashboard.

        Closing the tab without 'Stop Session' leaves the device held until the idle
        timeout, and the next session's stream never attaches.
        """
        page = self.page
        try:
            stop = page.get_by_text("Stop Session", exact=True)
            if stop.count():
                stop.first.click(timeout=5000)
                page.wait_for_timeout(2000)
                for label in ("Stop", "Yes", "Stop Session", "End Session", "Confirm"):
                    btn = page.get_by_role("button", name=label)
                    if btn.count():
                        try:
                            btn.last.click(timeout=3000)
                            break
                        except Exception:
                            continue
                page.wait_for_timeout(4000)
        except Exception:
            pass
        try:
            page.goto(DASHBOARD, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
        except Exception:
            pass

    def quit(self) -> None:
        try:
            self.end_session()
        except Exception:
            pass
        try:
            self.ctx.close()
        finally:
            self._pw.stop()
