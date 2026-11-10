"""Drive a real iPhone on BrowserStack App Automate with a vision model, over Appium.

iOS counterpart of ``mvp.android_agent``: each step takes a screenshot plus the
XCUITest element tree, the model picks one action, and Appium executes it. The
session starts in the App Store so the agent can sign in with the owner's Apple
ID (SMS 2FA via the ntfy relay), install the app under test, open it, and run
the task. Secrets are typed locally and never sent to the model.

    BROWSERSTACK_USERNAME=... BROWSERSTACK_ACCESS_KEY=... \
    python -m mvp.ios_agent --bundle-id com.glucobit.cravingBuster.CravingBuster \
        --task "Install Reframe from the App Store, then sign up and finish onboarding"
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from mvp.android_agent import SECRET_FIELDS, Element, _model_client, _wait_sms, decide

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "results" / "ios"
HUB = "https://hub-cloud.browserstack.com/wd/hub"
API = "https://api-cloud.browserstack.com/app-automate"
APP_STORE = "com.apple.AppStore"
SAMPLE_IPA_URL = "https://www.browserstack.com/app-automate/sample-apps/ios/BStackSampleApp.ipa"
SAMPLE_IPA = ROOT / "results" / "ios" / "BStackSampleApp.ipa"

_INTERACTIVE = {
    "Button", "TextField", "SecureTextField", "SearchField", "Cell", "Link", "Switch",
    "Tab", "Key", "TextView", "SegmentedControl", "Slider", "PickerWheel",
}

PROMPT = """You are a real person using an iPhone to accomplish a task.
Task: {task}

You see a screenshot and a list of on-screen elements (index, type, label).
Reply with ONE JSON object:
  {{"action": "tap", "element": <index>}}                      tap a listed element
  {{"action": "tap_point", "point": [x, y]}}                   tap; x,y normalized 0-1000
  {{"action": "type", "text": "..."}}                          type into the focused field
  {{"action": "type_secret", "field": "apple_email"|"apple_password"}}
  {{"action": "sms_code"}}         a verification code was texted; fetch and type it
  {{"action": "open_app", "app": "app_store"|"target"}}        bring an app to the front
  {{"action": "swipe", "direction": "up"|"down"}}
  {{"action": "back"}} | {{"action": "enter"}} | {{"action": "wait"}}
  {{"action": "done", "summary": "..."}}   task finished
  {{"action": "fail", "summary": "..."}}   truly stuck
Always add "reason": a short first-person note on what you see and why.
For Apple ID sign-in: never wait for approval on another device. Choose
"Didn't get a code?" / "Text Message" / "use phone number", then use sms_code.
Never type passwords with "type"; use "type_secret". Installs take a while: wait.

Recent steps:
{history}

Elements:
{elements}
"""


def parse_xcui(xml_text: str, limit: int = 60) -> list[Element]:
    """Visible, labelled or interactive nodes from an XCUITest page source (points)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: list[Element] = []
    for node in root.iter():
        if node.get("visible") != "true":
            continue
        try:
            x, y, w, h = (int(float(node.get(k) or 0)) for k in ("x", "y", "width", "height"))
        except ValueError:
            continue
        if w < 4 or h < 4:
            continue
        cls = node.tag.removeprefix("XCUIElementType")
        label = (node.get("label") or node.get("name") or node.get("value") or "").strip()
        clickable = cls in _INTERACTIVE
        editable = cls in {"TextField", "SecureTextField", "SearchField", "TextView"}
        if not label and not clickable:
            continue
        if not clickable and cls in {"Window", "Other", "Application"}:
            continue
        out.append(Element(len(out), label[:80], cls, (x + w // 2, y + h // 2), clickable, editable))
        if len(out) >= limit:
            break
    return out


def capabilities(name: str, device: str, os_version: str, app: str) -> dict[str, Any]:
    return {
        "platformName": "ios",
        "appium:automationName": "XCUITest",
        "appium:app": app,
        "appium:autoAcceptAlerts": False,
        "bstack:options": {
            "userName": os.environ["BROWSERSTACK_USERNAME"],
            "accessKey": os.environ["BROWSERSTACK_ACCESS_KEY"],
            "deviceName": device,
            "osVersion": os_version,
            "projectName": "UserSim",
            "buildName": "ios-agent",
            "sessionName": name[:255],
            "idleTimeout": 300,
            "interactiveDebugging": True,
        },
    }


def _api(path: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> dict:
    token = base64.b64encode(
        f"{os.environ['BROWSERSTACK_USERNAME']}:{os.environ['BROWSERSTACK_ACCESS_KEY']}".encode()
    ).decode()
    req = urllib.request.Request(f"{API}{path}", data=data, headers={"Authorization": f"Basic {token}", **(headers or {})})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read() or b"{}")


def upload_launcher(ipa: Path = SAMPLE_IPA, custom_id: str = "usersim-launcher") -> str:
    """App Automate needs an uploaded app to start a session; reuse a tiny sample app."""
    try:
        recent = _api(f"/recent_apps/{custom_id}")
        if isinstance(recent, list) and recent:
            return str(recent[0]["app_url"])
    except Exception:
        pass
    if not ipa.exists():
        ipa.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(SAMPLE_IPA_URL, ipa)
    boundary = f"----usersim{int(time.time())}"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"custom_id\"\r\n\r\n{custom_id}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{ipa.name}\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + ipa.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    out = _api("/upload", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return str(out["app_url"])


class Phone:
    def __init__(self, driver: Any) -> None:
        self.d = driver

    def screenshot(self) -> bytes:
        return base64.b64decode(self.d.get_screenshot_as_base64())

    def source(self) -> str:
        return self.d.page_source

    def size(self) -> tuple[int, int]:
        s = self.d.get_window_size()
        return int(s["width"]), int(s["height"])

    def tap(self, x: int, y: int) -> None:
        self.d.execute_script("mobile: tap", {"x": x, "y": y})

    def type_text(self, text: str) -> None:
        from appium.webdriver.common.appiumby import AppiumBy

        fields = self.d.find_elements(AppiumBy.IOS_PREDICATE, "hasKeyboardFocus == 1")
        if fields:
            fields[0].send_keys(text)
        else:
            self.d.execute_script("mobile: keys", {"keys": list(text)})

    def swipe(self, direction: str) -> None:
        self.d.execute_script("mobile: swipe", {"direction": "up" if direction == "up" else "down"})

    def back(self) -> None:
        self.d.back()

    def activate(self, bundle_id: str) -> None:
        self.d.activate_app(bundle_id)


def execute(phone: Phone, step: dict, elements: list[Element], size: tuple[int, int],
            state: dict, bundle_id: str) -> str:
    action = str(step.get("action") or "wait")
    if action == "tap":
        idx = step.get("element")
        if isinstance(idx, int) and 0 <= idx < len(elements):
            phone.tap(*elements[idx].center)
            return "ok"
        return "bad_element"
    if action == "tap_point":
        pt = step.get("point") or []
        if len(pt) == 2:
            phone.tap(int(pt[0] * size[0] / 1000), int(pt[1] * size[1] / 1000))
            return "ok"
        return "bad_point"
    if action == "type":
        phone.type_text(str(step.get("text") or ""))
        return "ok"
    if action == "type_secret":
        value = os.environ.get(SECRET_FIELDS.get(str(step.get("field")), ""))
        if not value:
            return "missing_secret"
        phone.type_text(value)
        return "ok"
    if action == "sms_code":
        since = state.setdefault("sms_since", time.time() - 60)
        code = _wait_sms(since)
        if not code:
            return "sms_timeout"
        state["sms_since"] = time.time()
        phone.type_text(code)
        return "ok"
    if action == "open_app":
        phone.activate(APP_STORE if step.get("app") == "app_store" else bundle_id)
        return "ok"
    if action == "swipe":
        phone.swipe(str(step.get("direction") or "up"))
        return "ok"
    if action == "back":
        phone.back()
        return "ok"
    if action == "enter":
        phone.type_text("\n")
        return "ok"
    if action == "wait":
        time.sleep(3)
        return "ok"
    return "terminal" if action in {"done", "fail"} else "unknown_action"


def run(task: str, bundle_id: str, *, device: str = "iPhone 15", os_version: str = "17",
        max_steps: int = 60, model: str | None = None, run_dir: Path | None = None) -> dict:
    from appium import webdriver
    from appium.options.common.base import AppiumOptions

    run_dir = run_dir or RUNS / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    options = AppiumOptions().load_capabilities(capabilities(task, device, os_version, upload_launcher()))
    driver = webdriver.Remote(HUB, options=options)
    session_id = driver.session_id
    phone = Phone(driver)
    client = _model_client()
    model = model or os.environ.get("MVP_IOS_MODEL", "gemini-2.5-flash")
    history: list[dict] = []
    state: dict[str, Any] = {}
    outcome: dict[str, Any] = {"ok": False, "reason": "max_steps"}
    try:
        installed = driver.is_app_installed(bundle_id)
        phone.activate(bundle_id if installed else APP_STORE)
        time.sleep(4)
        size = phone.size()
        for n in range(1, max_steps + 1):
            png = phone.screenshot()
            (run_dir / f"{n:02d}.png").write_bytes(png)
            elements = parse_xcui(phone.source())
            step = decide(client, model, task, png, elements, history, prompt=PROMPT)
            try:
                result = execute(phone, step, elements, size, state, bundle_id)
            except Exception as exc:  # stale element, transient Appium error: let the model retry
                result = f"error: {type(exc).__name__}"
            step.update(step=n, result=result, t=time.time())
            history.append(step)
            print(f"[{n:02d}] {step.get('action')} -> {result}: {str(step.get('reason', ''))[:100]}", flush=True)
            if result == "terminal":
                outcome = {"ok": step["action"] == "done", "reason": step["action"], "summary": step.get("summary")}
                break
            time.sleep(1.5)
        (run_dir / "final.png").write_bytes(phone.screenshot())
    finally:
        driver.execute_script(
            'browserstack_executor: {"action": "setSessionStatus", "arguments": '
            + json.dumps({"status": "passed" if outcome.get("ok") else "failed",
                          "reason": str(outcome.get("summary") or outcome.get("reason"))[:250]})
            + "}"
        )
        driver.quit()
    try:
        info = _api(f"/sessions/{session_id}.json").get("automation_session", {})
        outcome.update(public_url=info.get("public_url"), video_url=info.get("video_url"))
    except Exception:
        pass
    outcome.update(steps=len(history), run_dir=str(run_dir), session_id=session_id)
    (run_dir / "trace.json").write_text(json.dumps({"task": task, "bundle_id": bundle_id, "outcome": outcome, "history": history}, indent=2))
    return outcome


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--bundle-id", required=True)
    ap.add_argument("--device", default="iPhone 15")
    ap.add_argument("--os-version", default="17")
    ap.add_argument("--max-steps", type=int, default=60)
    ap.add_argument("--model")
    args = ap.parse_args()
    out = run(args.task, args.bundle_id, device=args.device, os_version=args.os_version,
              max_steps=args.max_steps, model=args.model)
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
