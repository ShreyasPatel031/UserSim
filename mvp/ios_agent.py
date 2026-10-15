"""Drive a real iPhone on BrowserStack App Automate with a vision + element loop.

Each step reads one screenshot and the on-screen accessibility elements, asks
Gemini for one action, and performs it through Appium (XCUITest). The same
loop installs apps from the App Store, signs in, and runs persona tasks.

Secrets never reach the model: it writes ``{{APPLE_ID}}`` / ``{{APPLE_PASSWORD}}``
and the driver substitutes them locally. Apple two-factor codes come from the
owner's forwarded SMS topic (``mvp.sms_provider`` ntfy backend).

Purchase guard: on any App Store payment or subscription sheet, taps on
confirm/subscribe/pay buttons and password entry are refused, and the run
records the paywall instead.

Env: BROWSERSTACK_USERNAME, BROWSERSTACK_ACCESS_KEY (or secrets/env.browserstack),
MVP_IOS_DEVICE (default "iPhone 15"), MVP_IOS_OS (default "17"),
MVP_IOS_MODEL (default "gemini-2.5-flash").
"""

from __future__ import annotations

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mvp.credentials import credentials_for_url

ROOT = Path(__file__).resolve().parents[1]
HUB = "https://hub-cloud.browserstack.com/wd/hub"
LAUNCHER_APP = "UserSimLauncher"  # custom_id of the placeholder .ipa App Automate needs
ELEMENT_CAP = 90

_INTERACTIVE = {
    "Button", "TextField", "SecureTextField", "SearchField", "Cell", "Link",
    "Switch", "Slider", "Key", "TextView", "Image", "StaticText", "Other",
    "PickerWheel", "SegmentedControl", "Tab", "MenuItem",
}

# Text that marks an App Store payment / subscription confirmation sheet.
_PURCHASE_SHEET = re.compile(
    r"(?i)(in-app purchase|confirm with side button|double[- ]click to (?:pay|subscribe|install)|"
    r"confirm subscription|subscription.*renews|you(?:'|’)re all set|apple pay|"
    r"\$\d+(?:\.\d{2})?\s*/\s*(?:year|month|week|yr|mo|wk))"
)
_CODE_SCREEN = re.compile(r"(?i)verification code|enter (?:the )?code|code (?:was )?sent|two-factor")
_PAY_BUTTON = re.compile(r"(?i)^(subscribe|purchase|buy|confirm|pay|pay now|start subscription)$")


def _load_bs_env() -> None:
    env_file = ROOT / "secrets" / "env.browserstack"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


@dataclass
class Element:
    idx: int
    kind: str
    label: str
    x: int
    y: int
    w: int
    h: int
    enabled: bool = True

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    def describe(self) -> str:
        flag = "" if self.enabled else " (disabled)"
        return f"[{self.idx}] {self.kind} \"{self.label[:70]}\" @({self.x},{self.y},{self.w}x{self.h}){flag}"


def parse_elements(source: str, screen_w: int, screen_h: int) -> list[Element]:
    """Visible, labelled elements on screen, deduplicated, in reading order."""
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return []
    out: list[Element] = []
    seen: set[tuple] = set()
    for node in root.iter():
        kind = node.tag.replace("XCUIElementType", "")
        if kind not in _INTERACTIVE or node.get("visible") != "true":
            continue
        label = (node.get("label") or node.get("name") or node.get("value") or "").strip()
        if kind in {"Other", "Image"} and (not label or node.get("accessible") != "true"):
            continue
        if not label and kind not in {"TextField", "SecureTextField", "SearchField", "TextView", "Button"}:
            continue
        try:
            x, y = int(node.get("x", 0)), int(node.get("y", 0))
            w, h = int(node.get("width", 0)), int(node.get("height", 0))
        except ValueError:
            continue
        if w <= 1 or h <= 1 or x >= screen_w or y >= screen_h or x + w <= 0 or y + h <= 0:
            continue
        key = (kind, label, x, y)
        if key in seen:
            continue
        seen.add(key)
        if kind == "SecureTextField":
            label = label or "password field"
        out.append(Element(0, kind, label, x, y, w, h, node.get("enabled") != "false"))
    out.sort(key=lambda e: (e.y, e.x))
    for i, el in enumerate(out[:ELEMENT_CAP], 1):
        el.idx = i
    return out[:ELEMENT_CAP]


class Device:
    """One BrowserStack App Automate iPhone session."""

    def __init__(self, *, session_name: str, build: str = "usersim-ios") -> None:
        _load_bs_env()
        from appium import webdriver
        from appium.options.common import AppiumOptions

        opts = AppiumOptions()
        opts.load_capabilities({
            "platformName": "ios",
            "appium:app": os.environ.get("MVP_IOS_LAUNCHER", LAUNCHER_APP),
            "appium:automationName": "XCUITest",
            "appium:autoAcceptAlerts": False,
            "bstack:options": {
                "userName": os.environ["BROWSERSTACK_USERNAME"],
                "accessKey": os.environ["BROWSERSTACK_ACCESS_KEY"],
                "deviceName": os.environ.get("MVP_IOS_DEVICE", "iPhone 15"),
                "osVersion": os.environ.get("MVP_IOS_OS", "17"),
                "projectName": "UserSim",
                "buildName": build,
                "sessionName": session_name,
                "idleTimeout": 300,
            },
        })
        self.driver = webdriver.Remote(HUB, options=opts)
        size = self.driver.get_window_size()
        self.w, self.h = int(size["width"]), int(size["height"])

    @property
    def session_id(self) -> str:
        return self.driver.session_id

    def observe(self) -> tuple[bytes, list[Element], str]:
        png = self.driver.get_screenshot_as_png()
        source = self.driver.page_source
        return png, parse_elements(source, self.w, self.h), source

    def tap_xy(self, x: int, y: int) -> None:
        self.driver.execute_script("mobile: tap", {"x": x, "y": y})

    def type_text(self, text: str, submit: bool = False) -> None:
        try:
            el = self.driver.switch_to.active_element
            el.send_keys(text)
        except Exception:
            self.driver.execute_script("mobile: keys", {"keys": list(text)})
        if submit:
            try:
                self.driver.switch_to.active_element.send_keys("\n")
            except Exception:
                pass

    def fill_secure(self, text: str) -> None:
        """Clear and fill the visible password field directly (avoids appending on retries)."""
        from appium.webdriver.common.appiumby import AppiumBy

        fields = [f for f in self.driver.find_elements(AppiumBy.CLASS_NAME, "XCUIElementTypeSecureTextField")
                  if f.is_displayed()]
        if not fields:
            self.type_text(text)
            return
        fields[0].click()
        fields[0].clear()
        fields[0].send_keys(text)

    def clear_focused(self) -> None:
        try:
            self.driver.switch_to.active_element.clear()
        except Exception:
            pass

    def swipe(self, direction: str) -> None:
        # mobile: swipe direction is the finger motion; "scroll down" = swipe up.
        finger = {"down": "up", "up": "down", "left": "left", "right": "right"}.get(direction, "up")
        self.driver.execute_script("mobile: swipe", {"direction": finger})

    def launch(self, bundle_id: str) -> None:
        self.driver.execute_script("mobile: launchApp", {"bundleId": bundle_id})

    def terminate(self, bundle_id: str) -> None:
        try:
            self.driver.execute_script("mobile: terminateApp", {"bundleId": bundle_id})
        except Exception:
            pass

    def remove(self, bundle_id: str) -> bool:
        try:
            return bool(self.driver.execute_script("mobile: removeApp", {"bundleId": bundle_id}))
        except Exception:
            return False

    def installed(self, bundle_id: str) -> bool:
        try:
            return bool(self.driver.execute_script("mobile: isAppInstalled", {"bundleId": bundle_id}))
        except Exception:
            return False

    def home(self) -> None:
        self.driver.execute_script("mobile: pressButton", {"name": "home"})

    def mark(self, passed: bool, reason: str) -> None:
        payload = {"action": "setSessionStatus", "arguments": {
            "status": "passed" if passed else "failed", "reason": reason[:250]}}
        try:
            self.driver.execute_script(f"browserstack_executor: {json.dumps(payload)}")
        except Exception:
            pass

    def quit(self) -> None:
        try:
            self.driver.quit()
        except Exception:
            pass


# --------------------------------------------------------------------------- model

_GEMINI = None


def _client():
    global _GEMINI
    if _GEMINI is None:
        from google import genai

        _GEMINI = genai.Client(
            vertexai=True,
            project=os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("VERTEX_LOCATION", "us-central1"),
        )
    return _GEMINI


ACTION_SPEC = """Reply with ONE JSON object:
{"thought": "<what you see and why this step, 1-2 sentences, in the persona's voice when acting as a persona>",
 "action": "tap" | "type" | "swipe" | "wait" | "reload" | "launch" | "home" | "request_code" | "request_email_code" | "done" | "give_up",
 "index": <element number for tap/type>,
 "point": [y, x]  (optional, for targets with no element: the tap point in the screenshot, normalized 0-1000
           with y first, the same convention as your bounding boxes),
 "text": "<text for type; use {{APPLE_ID}} / {{APPLE_PASSWORD}} for Apple credentials>",
 "submit": <true to press return after typing>,
 "direction": "down" | "up" | "left" | "right"  (swipe = scroll the content in that direction),
 "bundle_id": "<for launch>",
 "note": "<for done/give_up: outcome, what worked, what blocked you>"}
Rules:
- type taps the field first (by index, or by point [y, x] when the field has no element; always give one
  on a streamed phone), then types. Use it for text fields and search bars.
- request_email_code: use when the app emailed a verification code to your sign-up email; the system
  reads the inbox and types the code into the field at index (or the first text field).
- On a streamed phone (App Live), click the code field on the phone first, then use request_code /
  request_email_code; the code is typed into whatever is focused.
- request_code: use when Apple asks for a verification code sent by text; the system fills it in.
  If Apple shows a code prompt for your devices, tap "Didn't get a code?" then "Can't Get to Devices" /
  "Text the Code" to have it texted, then use request_code right away (don't tap resend repeatedly).
- NEVER confirm a payment, subscription, or in-app purchase. If a purchase or subscription sheet appears,
  close/cancel it and record what it asked for (price, trial length) in your thought.
- If asked how often to require the password for purchases, choose "Always Require".
- Accept reasonable permission prompts the way a normal user would (notifications: your choice;
  tracking: "Ask App Not to Track").
- Use give_up only when truly blocked."""


def _to_points(png: bytes, size: tuple[int, int] | None) -> bytes:
    """Downscale the retina screenshot to screen points so image x/y == tap x/y."""
    if not size:
        return png
    try:
        import io

        from PIL import Image

        im = Image.open(io.BytesIO(png)).convert("RGB").resize(size)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return png


def decide(goal: str, png: bytes, elements: list[Element], history: list[str], *,
           model: str | None = None, size: tuple[int, int] | None = None) -> dict:
    from google.genai import types

    png = _to_points(png, size)
    model_id = model or os.environ.get("MVP_IOS_MODEL", "gemini-2.5-flash")

    listing = "\n".join(e.describe() for e in elements) or "(no labelled elements)"
    for secret in _secret_values():
        listing = listing.replace(secret, "<redacted>")
    recent = "\n".join(history[-12:]) or "(first step)"
    prompt = (
        f"You are operating a real iPhone. The screenshot is {size[0] if size else '?'}x{size[1] if size else '?'} "
        "Prefer tapping by element index; use point [y, x] (0-1000) only for things missing from the element list.\n"
        f"GOAL:\n{goal}\n\nSTEPS SO FAR:\n{recent}\n\nON-SCREEN ELEMENTS:\n{listing}\n\n{ACTION_SPEC}"
    )
    resp = _client().models.generate_content(
        model=model_id,
        contents=[types.Part.from_text(text=prompt), types.Part.from_bytes(data=png, mime_type="image/png")],
        config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=1024,
            # Pro models reject a zero thinking budget.
            thinking_config=types.ThinkingConfig(thinking_budget=128 if "pro" in model_id else 0),
            response_mime_type="application/json",
        ),
    )
    raw = (resp.text or "").strip()
    match = re.search(r"\{.*\}", raw, re.S)
    try:
        data = json.loads(match.group(0) if match else raw)
    except Exception:
        return {"action": "wait", "thought": f"unparseable model reply: {raw[:120]}"}
    if isinstance(data, list):
        data = data[0] if data else {}
    return data if isinstance(data, dict) else {"action": "wait"}


# --------------------------------------------------------------------------- loop


@dataclass
class RunResult:
    ok: bool
    outcome: str
    note: str
    steps: list[dict] = field(default_factory=list)
    paywall: list[str] = field(default_factory=list)
    out_dir: str = ""


def _point(act: dict, dev: Any) -> tuple[int, int] | None:
    """Tap point from the model: ``point`` [y, x] normalized 0-1000, else legacy pixel x/y."""
    pt = act.get("point")
    try:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            y, x = float(pt[0]), float(pt[1])
            x, y = int(x / 1000 * dev.w), int(y / 1000 * dev.h)
        elif act.get("x") is not None and act.get("y") is not None:
            x, y = int(act["x"]), int(act["y"])
        else:
            return None
    except (TypeError, ValueError):
        return None
    return min(max(x, 1), dev.w - 1), min(max(y, 1), dev.h - 1)


def _secret_values() -> list[str]:
    """Every vault password, so none can reach the model through screen text."""
    from mvp.credentials import _load_vault

    return [str(site.get("password")) for site in _load_vault().get("sites") or [] if site.get("password")]


def _apple_creds() -> dict[str, str]:
    creds = credentials_for_url("https://account.apple.com") or {}
    return {"{{APPLE_ID}}": creds.get("username", ""), "{{APPLE_PASSWORD}}": creds.get("password", "")}


def _wait_sms(since: float, timeout_s: float = 240.0) -> str | None:
    from mvp.sms_provider import Number, wait_for_sms

    return wait_for_sms(Number(phone="", backend="ntfy"), timeout_s=timeout_s, newer_than=since)


CODE_DROP = ROOT / "secrets" / "email_codes"


def _wait_email(alias: str, since: float, timeout_s: float | None = None) -> str | None:
    """Code emailed to ``alias``.

    Read over IMAP where imap.gmail.com:993 is reachable. Where it is not
    (sandboxed cloud sessions), the run writes ``<alias>.wanted`` under
    secrets/email_codes/ and waits for an operator — e.g. a Gmail connector
    on the controlling session — to drop the code in ``<alias>.txt``.
    """
    use_imap = os.environ.get("MVP_EMAIL_DROP", "0") != "1"
    timeout_s = timeout_s or float(os.environ.get("MVP_EMAIL_WAIT_S", "180"))
    CODE_DROP.mkdir(parents=True, exist_ok=True)
    wanted, drop = CODE_DROP / f"{alias}.wanted", CODE_DROP / f"{alias}.txt"
    wanted.write_text(str(int(since)))
    started = time.time()
    try:
        while time.time() - started < timeout_s:
            if drop.is_file() and drop.stat().st_mtime >= since:
                code = re.sub(r"\D", "", drop.read_text())
                if code:
                    return code
            if use_imap:
                from mvp.email_codes import latest_signup_code

                code = latest_signup_code(alias, newer_than=since)
                if code:
                    return code
            time.sleep(3)
        return None
    finally:
        wanted.unlink(missing_ok=True)


def run_goal(
    dev: Device,
    goal: str,
    *,
    email_alias: str | None = None,
    out_dir: Path,
    max_steps: int = 40,
    budget_s: float = 900.0,
    allow_password: bool = True,
    min_steps: int = 0,
    stop_when: Any = None,
    log: Any = print,
) -> RunResult:
    """Pursue ``goal`` on the device until the model says done/give_up or limits hit."""
    out_dir.mkdir(parents=True, exist_ok=True)
    secrets = _apple_creds()
    history: list[str] = []
    steps: list[dict] = []
    paywall: list[str] = []
    started = time.monotonic()
    started_wall = time.time()
    last_submit_t = time.time()
    last_code_t = 0.0
    stuck = 0
    last_sig = ""

    for n in range(1, max_steps + 1):
        if time.monotonic() - started > budget_s:
            return RunResult(False, "timeout", "time budget exhausted", steps, paywall, str(out_dir))
        try:
            png, elements, source = dev.observe()
        except Exception as exc:
            return RunResult(False, "device_error", f"{type(exc).__name__}: {exc}"[:300], steps, paywall, str(out_dir))
        shot = out_dir / f"{n:02d}.png"
        shot.write_bytes(png)
        screen_text = " ".join(e.label for e in elements)
        purchase_sheet = bool(_PURCHASE_SHEET.search(screen_text))
        if purchase_sheet:
            paywall.append(screen_text[:400])

        if stop_when is not None:
            try:
                if stop_when(dev, elements, source):
                    return RunResult(True, "done", "stop condition met", steps, paywall, str(out_dir))
            except Exception:
                pass

        # Apple two-factor screen: fill a freshly texted code without asking the model.
        if _CODE_SCREEN.search(screen_text) and time.time() - last_code_t > 20:
            code = _wait_sms(max(last_submit_t - 30, last_code_t), timeout_s=4)
            if code:
                field_el = next((e for e in elements if e.kind in {"TextField", "SecureTextField"}), None)
                if field_el:
                    dev.tap_xy(*field_el.center)
                    time.sleep(0.5)
                dev.type_text(code)
                last_code_t = time.time()
                steps.append({"step": n, "action": "auto_code", "thought": "filled texted Apple code", "shot": shot.name})
                history.append(f"{n}. auto-filled the Apple verification code that arrived by text")
                log(f"  {n}. auto_code")
                time.sleep(4)
                continue

        sig = str(hash(screen_text))
        stuck = stuck + 1 if sig == last_sig else 0
        last_sig = sig
        extra = ""
        if stuck >= 3:
            extra = "\nNOTE: the screen has not changed for 3 steps; try something different."
        if purchase_sheet:
            extra += "\nNOTE: a purchase/subscription sheet is showing. Do NOT confirm. Cancel or dismiss it."

        try:
            act = decide(goal + extra, png, elements, history, size=(dev.w, dev.h))
        except Exception as exc:
            act = {"action": "wait", "thought": f"model error {type(exc).__name__}"}
        action = str(act.get("action") or "wait").lower()
        thought = str(act.get("thought") or "")[:400]
        record: dict[str, Any] = {"step": n, "action": action, "thought": thought, "shot": shot.name}

        el: Element | None = None
        if act.get("index") is not None:
            try:
                el = next((e for e in elements if e.idx == int(act["index"])), None)
            except (TypeError, ValueError):
                el = None
        if el:
            record["target"] = f"{el.kind} \"{el.label[:60]}\""

        try:
            if action == "tap":
                if el and purchase_sheet and _PAY_BUTTON.match(el.label.strip()):
                    record["blocked"] = "purchase confirmation refused"
                    history.append(f"{n}. BLOCKED tap on '{el.label}' (purchase guard). Cancel the sheet instead.")
                elif el:
                    dev.tap_xy(*el.center)
                    if re.search(r"(?i)sign in|continue|next|get|install|send|verify|text|code|call", el.label):
                        last_submit_t = time.time()
                elif _point(act, dev) is not None:
                    x, y = _point(act, dev)
                    dev.tap_xy(x, y)
                    record["target"] = f"({x},{y})"
            elif action == "type":
                text = str(act.get("text") or "")
                uses_password = "{{APPLE_PASSWORD}}" in text
                prev_pw = bool(steps) and steps[-1].get("action") == "type" and steps[-1].get("password")
                if uses_password and (purchase_sheet or not allow_password):
                    record["blocked"] = "password refused on purchase sheet"
                    history.append(f"{n}. BLOCKED password entry (purchase guard).")
                elif uses_password and el and el.kind != "SecureTextField":
                    record["blocked"] = "password only goes in a password field"
                    history.append(f"{n}. BLOCKED: the password goes only into a SecureTextField (password field).")
                elif uses_password and prev_pw:
                    # Secure fields render empty, so the model tends to retype; submit instead.
                    button = next((e for e in elements if e.kind == "Button" and re.fullmatch(
                        r"(?i)sign in|continue|next|log ?in|done", e.label.strip())), None)
                    if button:
                        dev.tap_xy(*button.center)
                        last_submit_t = time.time()
                        record["action"], record["target"] = "tap", f"Button \"{button.label}\" (auto-submit)"
                    history.append(f"{n}. password was already typed; tapped submit instead of retyping")
                else:
                    real = text
                    for key, value in secrets.items():
                        real = real.replace(key, value)
                    if el and el.kind == "SecureTextField":
                        dev.fill_secure(real)
                    else:
                        if el:
                            dev.tap_xy(*el.center)
                            time.sleep(0.6)
                            dev.clear_focused()
                        elif _point(act, dev) is not None:
                            # Streamed phone: focus the field by tapping where it is.
                            dev.tap_xy(*_point(act, dev))
                            time.sleep(0.8)
                        dev.type_text(real, submit=bool(act.get("submit")))
                    if act.get("submit"):
                        last_submit_t = time.time()
                    record["text"] = "<secret>" if real != text else text
                    if uses_password:
                        record["password"] = True
                        record["note"] = ("password typed (secure fields look empty in screenshots); "
                                          "next tap Sign In / Continue, do not retype")
            elif action == "swipe":
                dev.swipe(str(act.get("direction") or "down"))
                record["direction"] = act.get("direction")
            elif action == "launch":
                if getattr(dev, "stream_only", False):
                    history.append(f"{n}. launch is not available on this phone; use the phone's own UI.")
                else:
                    dev.launch(str(act.get("bundle_id") or ""))
            elif action == "home":
                dev.home()
            elif action == "reload":
                if hasattr(dev, "reload"):
                    dev.reload()
            elif action == "request_code":
                log("    waiting for Apple SMS code via ntfy…")
                code = _wait_sms(max(last_submit_t - 30, last_code_t), timeout_s=90)
                if not code:
                    record["error"] = "no sms code"
                    history.append(f"{n}. request_code: NO CODE ARRIVED")
                else:
                    target = el or (None if getattr(dev, "stream_only", False) else next((e for e in elements if e.kind in {"TextField", "SecureTextField"}), None))
                    if target:
                        dev.tap_xy(*target.center)
                        time.sleep(0.5)
                    dev.type_text(code)
                    record["text"] = "<sms code>"
                    last_code_t = last_submit_t = time.time()
            elif action == "request_email_code":
                if not email_alias:
                    record["error"] = "no email alias for this run"
                else:
                    log(f"    waiting for email code to {email_alias}…")
                    code = _wait_email(email_alias, started_wall - 60)
                    if not code:
                        record["error"] = "no email code"
                    else:
                        target = el or (None if getattr(dev, "stream_only", False) else next((e for e in elements if e.kind in {"TextField", "SecureTextField"}), None))
                        if target:
                            dev.tap_xy(*target.center)
                            time.sleep(0.5)
                        dev.type_text(code)
                        record["text"] = "<email code>"
            elif action == "give_up" and n < min_steps:
                # Too early to quit: usually a misread screen (streamed taps lag), not a real dead end.
                record["blocked"] = "give_up refused (too early)"
                history.append(f"{n}. give_up refused: only {n} steps in. Look again at the current screen — "
                               "taps can take a moment to show — and keep going.")
            elif action in {"done", "give_up"}:
                record["note"] = str(act.get("note") or "")
                steps.append(record)
                (out_dir / "trace.json").write_text(json.dumps(steps, indent=2))
                return RunResult(action == "done", action, record["note"], steps, paywall, str(out_dir))
            else:
                time.sleep(2)
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"[:200]

        steps.append(record)
        line = f"{n}. {action} {record.get('target', '')} {record.get('text', '')} — {thought[:140]}"
        if record.get("note"):
            line += f" [{record['note']}]"
        if record.get("error"):
            line += f" [error: {record['error'][:80]}]"
        history.append(line)
        log(f"  {line}")
        (out_dir / "trace.json").write_text(json.dumps(steps, indent=2))
        time.sleep(getattr(dev, "settle_s", 1.2))

    return RunResult(False, "max_steps", "step limit reached", steps, paywall, str(out_dir))
