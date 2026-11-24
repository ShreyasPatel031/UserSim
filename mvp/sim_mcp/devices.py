"""Real phones for simulated users: Android (and later iOS) apps on LambdaTest real devices.

A caller gives an app (an https:// link to an .apk, or an lt://APP... id from an earlier
upload); the server uploads it to LambdaTest if needed, starts a real device over Appium (W3C WebDriver, spoken
directly over HTTPS so no Appium client is needed), and the model drives it with observe / act, like the browser
tools. Credentials: LT_USERNAME / LT_ACCESS_KEY (Secret Manager usersim-LT_USERNAME / usersim-LT_ACCESS_KEY, hot
reloaded by mvp/secrets_store.py). Never logged or returned.

Caps (limits.json): devices_enabled, device_max_concurrent (LambdaTest plan parallel limit), device_session_max_s,
device_max_steps, est_usd_per_device_session / est_usd_per_device_step (charged against anonymous daily budgets),
anon_daily_app_uploads_per_ip.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import re
import secrets
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

import httpx

HUB = "https://mobile-hub.lambdatest.com/wd/hub"
UPLOAD = "https://manual-api.lambdatest.com/app/upload/realDevice"
_LOCK = threading.Lock()
DEVICES: dict[str, "DeviceSession"] = {}
_UPLOADS: dict[str, list[float]] = {}


class DeviceError(Exception):
    pass


def creds() -> tuple[str, str]:
    u, k = os.environ.get("LT_USERNAME", "").strip(), os.environ.get("LT_ACCESS_KEY", "").strip()
    if not (u and k):
        raise DeviceError("real devices are not configured on this server yet (LambdaTest credentials missing)")
    return u, k


def _lim(key: str) -> Any:
    from mvp.sim_mcp import limits as L

    return L.get(key)


# ---- app upload -------------------------------------------------------------------------------------------------
APP_ID = re.compile(r"^lt://[A-Za-z0-9]{8,64}$")


def resolve_app(app: str, owner: str = "") -> str:
    """lt://... passes through; an https:// link to an .apk/.aab/.ipa is uploaded to LambdaTest by URL."""
    app = (app or "").strip()
    if APP_ID.match(app):
        return app
    if not app.startswith("https://"):
        raise DeviceError("app must be an lt://APP... id or an https:// link to the .apk / .ipa file")
    from mvp.sim_mcp.sessions import is_anon

    if is_anon(owner):
        cap = int(_lim("anon_daily_app_uploads_per_ip"))
        day = time.strftime("%Y-%m-%d")
        key = f"{owner}|{day}"
        with _LOCK:
            n = _UPLOADS.setdefault(key, [])
            if len(n) >= cap:
                raise DeviceError(f"cap anon_daily_app_uploads_per_ip: {cap} app uploads a day without a token; "
                                  "reuse the lt://APP id from an earlier upload")
            n.append(time.time())
    u, k = creds()
    r = httpx.post(UPLOAD, auth=(u, k), data={"url": app, "name": "atelier-sim"}, timeout=300)
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 300 or not j.get("app_url"):
        raise DeviceError(f"LambdaTest could not take that app ({r.status_code}): "
                          f"{(j.get('message') or r.text)[:200]}. The link must download the .apk/.ipa file itself.")
    return j["app_url"]


def upload_file(data: bytes, filename: str) -> str:
    """Upload app bytes to LambdaTest and return its lt:// id."""
    if not data.startswith(b"PK"):
        raise DeviceError("not an .apk / .aab / .ipa file (zip expected)")
    u, k = creds()
    r = httpx.post(UPLOAD, auth=(u, k), data={"name": filename[:80] or "atelier-sim"},
                   files={"appFile": (filename or "app.apk", data)}, timeout=600)
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 300 or not j.get("app_url"):
        raise DeviceError(f"LambdaTest upload failed ({r.status_code}): {(j.get('message') or r.text)[:200]}")
    return j["app_url"]


# ---- device session ---------------------------------------------------------------------------------------------
@dataclass
class DeviceSession:
    id: str
    owner: str
    app: str
    platform: str
    task: str
    persona: str
    wd: str = ""  # WebDriver session id
    device: str = ""
    os_version: str = ""
    started: float = field(default_factory=time.time)
    last: float = field(default_factory=time.time)
    steps: list[dict[str, Any]] = field(default_factory=list)
    shot_size: tuple[int, int] = (0, 0)
    closed: bool = False
    outcome: str = ""
    notes: str = ""

    # W3C WebDriver over HTTPS
    def _call(self, method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 60) -> Any:
        u, k = creds()
        url = f"{HUB}/session/{self.wd}{path}" if self.wd else f"{HUB}{path}"
        r = httpx.request(method, url, auth=(u, k), json=body, timeout=timeout)
        try:
            j = r.json()
        except ValueError:
            raise DeviceError(f"device hub answered {r.status_code}")
        v = j.get("value")
        if r.status_code >= 300:
            msg = v.get("message") if isinstance(v, dict) else str(v)
            raise DeviceError(f"device error: {str(msg)[:300]}")
        return v

    def start(self, device: str = "", os_version: str = "") -> None:
        caps = {"platformName": self.platform, "isRealMobile": True, "app": self.app, "w3c": True,
                "build": "atelier-sim", "name": f"atelier-sim {self.id[:8]}", "idleTimeout": 180,
                "autoGrantPermissions": True, "autoAcceptAlerts": False,
                "deviceName": device or (".*" if self.platform == "android" else "iPhone.*")}
        if os_version:
            caps["platformVersion"] = os_version
        v = self._call("POST", "/session", {"capabilities": {"alwaysMatch": {"lt:options": caps}}}, timeout=300)
        self.wd = v.get("sessionId") or ""
        c = v.get("capabilities") or {}
        self.device, self.os_version = str(c.get("deviceName") or ""), str(c.get("platformVersion") or "")
        if not self.wd:
            raise DeviceError("no device session id")

    def screenshot(self) -> bytes:
        return base64.b64decode(self._call("GET", "/screenshot"))

    def elements(self, limit: int = 80) -> list[dict[str, Any]]:
        try:
            root = ET.fromstring(self._call("GET", "/source").encode())
        except Exception:  # noqa: BLE001
            return []
        out = []
        for e in root.iter():
            a = e.attrib
            label = (a.get("text") or a.get("content-desc") or a.get("label") or a.get("name") or "").strip()
            clickable = a.get("clickable") == "true" or e.tag.endswith(("Button", "EditText", "TextField"))
            if not label and not clickable:
                continue
            m = re.findall(r"\d+", a.get("bounds", ""))
            if len(m) == 4:
                x1, y1, x2, y2 = map(int, m)
            else:
                try:
                    x1, y1 = int(a.get("x", 0)), int(a.get("y", 0))
                    x2, y2 = x1 + int(a.get("width", 0)), y1 + int(a.get("height", 0))
                except ValueError:
                    continue
            if x2 <= x1 or y2 <= y1:
                continue
            kind = e.tag.split(".")[-1].replace("XCUIElementType", "")
            out.append({"kind": kind, "label": label[:80], "x": (x1 + x2) // 2, "y": (y1 + y2) // 2,
                        **({"input": True} if "EditText" in kind or "TextField" in kind else {})})
            if len(out) >= limit:
                break
        return out

    def _pointer(self, moves: list[dict[str, Any]]) -> None:
        self._call("POST", "/actions", {"actions": [{"type": "pointer", "id": "finger1",
                                                     "parameters": {"pointerType": "touch"}, "actions": moves}]})
        self._call("DELETE", "/actions")

    def tap(self, x: int, y: int) -> None:
        self._pointer([{"type": "pointerMove", "duration": 0, "x": x, "y": y}, {"type": "pointerDown", "button": 0},
                       {"type": "pause", "duration": 80}, {"type": "pointerUp", "button": 0}])

    def swipe(self, direction: str) -> None:
        w, h = self.shot_size if self.shot_size[0] else (1080, 2000)
        cx, top, bot = w // 2, int(h * 0.25), int(h * 0.75)
        a, b = {"up": ((cx, bot), (cx, top)), "down": ((cx, top), (cx, bot)),
                "left": ((int(w * .85), h // 2), (int(w * .15), h // 2)),
                "right": ((int(w * .15), h // 2), (int(w * .85), h // 2))}[direction]
        self._pointer([{"type": "pointerMove", "duration": 0, "x": a[0], "y": a[1]}, {"type": "pointerDown", "button": 0},
                       {"type": "pointerMove", "duration": 400, "x": b[0], "y": b[1]}, {"type": "pointerUp", "button": 0}])

    def type_text(self, text: str) -> None:
        el = self._call("GET", "/element/active")
        eid = next(iter(el.values())) if isinstance(el, dict) and el else None
        if not eid:
            raise DeviceError("no text field is focused: tap the field first")
        self._call("POST", f"/element/{eid}/value", {"text": text})

    def key(self, name: str) -> None:
        if self.platform == "android":
            code = {"back": 4, "home": 3, "enter": 66}.get(name)
            if code is None:
                raise DeviceError("key must be back, home or enter")
            self._call("POST", "/appium/device/press_keycode", {"keycode": code})
        else:
            self._call("POST", "/execute/sync", {"script": "mobile: pressButton", "args": [{"name": "home"}]})

    def quit(self) -> None:
        if self.wd and not self.closed:
            try:
                self._call("DELETE", "", timeout=30)
            except Exception:  # noqa: BLE001
                pass
        self.closed = True


def jpeg(png: bytes, width: int = 540) -> tuple[bytes, float]:
    """Downscale for the model; returns (jpeg, scale) where model coordinates * scale = device pixels."""
    from PIL import Image

    im = Image.open(io.BytesIO(png)).convert("RGB")
    s = im.width / width if im.width > width else 1.0
    if s != 1.0:
        im = im.resize((width, round(im.height / s)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=70)
    return buf.getvalue(), s


# ---- API used by the MCP tools ----------------------------------------------------------------------------------
def open_count() -> int:
    return sum(1 for d in DEVICES.values() if not d.closed)


def reap() -> None:
    now = time.time()
    cap_s = float(_lim("device_session_max_s"))
    for d in list(DEVICES.values()):
        if not d.closed and (now - d.started > cap_s or now - d.last > 240):
            d.quit()
            d.outcome = d.outcome or "timeout"


async def start(owner: str, app: str, task: str, persona: str, platform: str = "android", device: str = "",
                os_version: str = "") -> DeviceSession:
    if not bool(_lim("devices_enabled")):
        raise DeviceError("real devices are switched off on this server (limits.json devices_enabled)")
    platform = (platform or "android").lower()
    if platform not in ("android", "ios"):
        raise DeviceError("platform must be android or ios")
    await asyncio.to_thread(reap)
    if open_count() >= int(_lim("device_max_concurrent")):
        raise DeviceError("all real devices are busy; retry in a minute")
    lt_app = await asyncio.to_thread(resolve_app, app, owner)
    d = DeviceSession(id=secrets.token_hex(12), owner=owner, app=lt_app, platform=platform, task=task, persona=persona)
    DEVICES[d.id] = d
    try:
        await asyncio.to_thread(d.start, device, os_version)
    except Exception:
        DEVICES.pop(d.id, None)
        raise
    return d


def get(session_id: str, owner: str, allow_closed: bool = False) -> DeviceSession:
    from mvp.sim_mcp.sessions import same_owner

    d = DEVICES.get(session_id)
    if d is None or not same_owner(d.owner, owner):
        raise DeviceError(f"unknown device session_id {session_id!r}")
    if allow_closed:
        return d
    if d.closed:
        raise DeviceError(f"device session {session_id} is closed ({d.outcome or 'finished'})")
    if time.time() - d.started > float(_lim("device_session_max_s")):
        d.quit()
        d.outcome = "timeout"
        raise DeviceError("device session time is up: call usersim_device_finish")
    return d


async def observe(d: DeviceSession) -> dict[str, Any]:
    png = await asyncio.to_thread(d.screenshot)
    img, scale = await asyncio.to_thread(jpeg, png)
    from PIL import Image

    with Image.open(io.BytesIO(png)) as im:
        d.shot_size = im.size
    els = await asyncio.to_thread(d.elements)
    for e in els:
        e["x"], e["y"] = round(e["x"] / scale), round(e["y"] / scale)
    d.last = time.time()
    left = int(float(_lim("device_session_max_s")) - (time.time() - d.started))
    return {"jpeg": img, "scale": scale, "meta": {"session_id": d.id, "step": len(d.steps), "device": d.device,
            "os": d.os_version, "seconds_left": left, "steps_left": int(_lim("device_max_steps")) - len(d.steps),
            "elements": els, "coordinates": "x, y in this screenshot's pixels"}}


async def act(d: DeviceSession, action: str, thought: str, x: int | None = None, y: int | None = None,
              text: str | None = None, direction: str | None = None, key: str | None = None) -> None:
    if len(d.steps) >= int(_lim("device_max_steps")):
        raise DeviceError("step limit reached: call usersim_device_finish")
    scale = d.shot_size[0] / 540 if d.shot_size[0] > 540 else 1.0
    a = (action or "").lower()
    if a == "tap":
        if x is None or y is None:
            raise DeviceError("tap needs x and y (screenshot pixels)")
        await asyncio.to_thread(d.tap, round(int(x) * scale), round(int(y) * scale))
    elif a == "type":
        await asyncio.to_thread(d.type_text, text or "")
    elif a == "swipe":
        if direction not in ("up", "down", "left", "right"):
            raise DeviceError("swipe needs direction up/down/left/right")
        await asyncio.to_thread(d.swipe, direction)
    elif a == "key":
        await asyncio.to_thread(d.key, (key or "").lower())
    elif a == "wait":
        await asyncio.sleep(min(10.0, float(text or 3)))
    else:
        raise DeviceError("action must be tap, type, swipe, key or wait")
    d.steps.append({"step": len(d.steps) + 1, "action": a, "x": x, "y": y, "text": text if a != "type" else "…",
                    "direction": direction, "key": key, "thought": thought[:500], "t": round(time.time() - d.started, 1)})
    d.last = time.time()
    await asyncio.sleep(0.8)


def finish(d: DeviceSession, outcome: str, notes: str) -> dict[str, Any]:
    d.outcome, d.notes = outcome, notes[:2000]
    d.quit()
    return {"session_id": d.id, "outcome": outcome, "device": d.device, "os": d.os_version,
            "steps": d.steps, "seconds": round(time.time() - d.started), "app": d.app}
