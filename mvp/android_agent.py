"""Drive an Android app on an emulator/device with a vision model, over adb.

The browser agents only see web pages; this is the mobile counterpart used to
run a study task inside a native app (e.g. Reframe). Each step: screenshot +
uiautomator element list -> model picks one action -> adb executes it.

Secrets never reach the model. It asks for ``type_secret`` with a field name
(``apple_email`` / ``apple_password``) and the agent types the value itself;
``sms_code`` waits for the next forwarded SMS code (ntfy relay) and types it.

    python -m mvp.android_agent --package com.glucobit.reframe --apk-dir apks/ \
        --task "Sign up with Apple and finish onboarding"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "results" / "android"

SECRET_FIELDS = {
    "apple_email": "APPLE_ID_EMAIL",
    "apple_password": "APPLE_ID_PASSWORD",
    "google_email": "SIGNUP_GMAIL_USER",
    "google_password": "SIGNUP_GMAIL_PASSWORD",
    "app_email": "APP_SIGNUP_EMAIL",
    "app_password": "APP_SIGNUP_PASSWORD",
}
TOTP_ENV = "SIGNUP_GMAIL_TOTP_SECRET"

_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


@dataclass
class Element:
    index: int
    label: str
    cls: str
    center: tuple[int, int]
    clickable: bool
    editable: bool


def adb_text_arg(text: str) -> str:
    """Escape text for ``adb shell input text`` (spaces become %s)."""
    return shlex.quote(text.replace("%", "\\%").replace(" ", "%s"))


def parse_ui(xml_text: str, limit: int = 60) -> list[Element]:
    """Visible, labelled or interactive nodes from a uiautomator dump."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: list[Element] = []
    for node in root.iter("node"):
        m = _BOUNDS.match(node.get("bounds") or "")
        if not m:
            continue
        x0, y0, x1, y1 = map(int, m.groups())
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        label = (node.get("text") or node.get("content-desc") or node.get("resource-id") or "").strip()
        clickable = node.get("clickable") == "true"
        cls = (node.get("class") or "").rsplit(".", 1)[-1]
        editable = cls == "EditText"
        if not label and not (clickable or editable):
            continue
        out.append(
            Element(len(out), label[:80], cls, ((x0 + x1) // 2, (y0 + y1) // 2), clickable, editable)
        )
        if len(out) >= limit:
            break
    return out


class Adb:
    def __init__(self, serial: str | None = None) -> None:
        sdk = os.environ.get("ANDROID_HOME") or str(Path.home() / "android-sdk")
        exe = Path(sdk) / "platform-tools" / "adb"
        self.base = [str(exe) if exe.exists() else "adb"] + (["-s", serial] if serial else [])

    def run(self, *args: str, timeout: float = 60.0) -> bytes:
        return subprocess.run(
            self.base + list(args), capture_output=True, timeout=timeout, check=False
        ).stdout

    def shell(self, cmd: str, timeout: float = 60.0) -> str:
        return self.run("shell", cmd, timeout=timeout).decode(errors="replace")

    def screencap(self) -> bytes:
        return self.run("exec-out", "screencap", "-p")

    def ui_xml(self) -> str:
        self.shell("uiautomator dump /sdcard/ui.xml >/dev/null 2>&1")
        return self.shell("cat /sdcard/ui.xml")

    def size(self) -> tuple[int, int]:
        m = re.search(r"(\d+)x(\d+)", self.shell("wm size"))
        return (int(m.group(1)), int(m.group(2))) if m else (1080, 2400)

    def tap(self, x: int, y: int) -> None:
        self.shell(f"input tap {x} {y}")

    def type_text(self, text: str) -> None:
        self.shell(f"input text {adb_text_arg(text)}")

    def key(self, name: str) -> None:
        self.shell(f"input keyevent {shlex.quote(name)}")

    def swipe(self, direction: str) -> None:
        w, h = self.size()
        cx, top, bottom = w // 2, int(h * 0.3), int(h * 0.75)
        y0, y1 = (bottom, top) if direction == "up" else (top, bottom)
        self.shell(f"input swipe {cx} {y0} {cx} {y1} 400")

    def install(self, apk_paths: list[Path]) -> str:
        args = ["install-multiple", "-r"] if len(apk_paths) > 1 else ["install", "-r"]
        return self.run(*args, *map(str, apk_paths), timeout=300).decode(errors="replace")

    def launch(self, package: str) -> None:
        self.shell(f"monkey -p {shlex.quote(package)} -c android.intent.category.LAUNCHER 1")

    def has_package(self, package: str) -> bool:
        return f"package:{package}" in self.shell(f"pm list packages {shlex.quote(package)}")


def apks_in(path: Path) -> list[Path]:
    """APK files to install, unpacking an .xapk/.apkm bundle if that is what we have."""
    if path.is_file() and path.suffix == ".apk":
        return [path]
    files = sorted(path.glob("*.apk")) if path.is_dir() else []
    if files:
        return files
    bundles = sorted(path.glob("*.xapk")) + sorted(path.glob("*.apkm")) if path.is_dir() else [path]
    for bundle in bundles:
        import zipfile

        dest = bundle.with_suffix("")
        dest.mkdir(exist_ok=True)
        with zipfile.ZipFile(bundle) as zf:
            for name in zf.namelist():
                if name.endswith(".apk"):
                    zf.extract(name, dest)
        return sorted(dest.rglob("*.apk"))
    return []


PROMPT = """You are a real person using an Android app to accomplish a task.
Task: {task}

You see a screenshot and a list of on-screen elements (index, class, label).
Reply with ONE JSON object:
  {{"action": "tap", "element": <index>}}                      tap a listed element
  {{"action": "tap_point", "point": [x, y]}}                   tap; x,y normalized 0-1000
  {{"action": "type", "text": "..."}}                          type into the focused field
  {{"action": "type_secret", "field": "apple_email"|"apple_password"|"google_email"|"google_password"|"app_email"|"app_password"}}
  {{"action": "email_code"}}       a code was emailed to app_email; fetch and type it
  {{"action": "email_link"}}       a verification link was emailed to app_email; open it
  {{"action": "sms_code"}}         a verification code was texted; fetch and type it
  {{"action": "totp_code"}}        Google asks for an authenticator-app code; type it
  {{"action": "swipe", "direction": "up"|"down"}}
  {{"action": "back"}} | {{"action": "enter"}} | {{"action": "wait"}}
  {{"action": "done", "summary": "..."}}   task finished
  {{"action": "fail", "summary": "..."}}   truly stuck
Always add "reason": a short first-person note on what you see and why.
For Apple ID prompts, prefer "Text code"/"use phone number" over device approval.
Never type passwords with "type"; use "type_secret".
For type, type_secret, sms_code, totp_code and email_code include "element": <id of the input field> so it is focused first.

Recent steps:
{history}

Elements:
{elements}
"""


def _model_client() -> Any:
    from google import genai

    return genai.Client(
        vertexai=True,
        project=os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT"),
        location=os.environ.get("VERTEX_LOCATION", "us-central1"),
    )


def decide(client: Any, model: str, task: str, png: bytes, elements: list[Element], history: list[dict],
           prompt: str = PROMPT) -> dict:
    from google.genai import types

    els = "\n".join(
        f"[{e.index}] {e.cls}{' (input)' if e.editable else ''}{' (tap)' if e.clickable else ''}: {e.label}"
        for e in elements
    )
    hist = "\n".join(f"- {h['action']}: {h.get('reason', '')}" for h in history[-8:]) or "(none)"
    resp = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=png, mime_type="image/png"),
            prompt.format(task=task, history=hist, elements=els or "(none)"),
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
    )
    try:
        data = json.loads(resp.text or "{}")
    except json.JSONDecodeError:
        return {"action": "wait", "reason": "unparseable model reply"}
    if isinstance(data, list):
        data = data[0] if data else {}
    return data if isinstance(data, dict) else {"action": "wait"}


def _wait_email(alias: str, since: float, link: bool) -> str | None:
    from mvp import email_codes

    wait = email_codes.wait_for_signup_link if link else email_codes.wait_for_signup_code
    return wait(alias, newer_than=since, timeout_s=float(os.environ.get("MVP_EMAIL_WAIT_S", "240")))


def _wait_sms(since: float) -> str | None:
    from mvp.apple_signin import _wait_sms_code

    return _wait_sms_code(since, float(os.environ.get("MVP_SMS_WAIT_S", "300")))


TYPING_ACTIONS = ("type", "type_secret", "sms_code", "totp_code", "email_code")


def execute(adb: Adb, step: dict, elements: list[Element], size: tuple[int, int], state: dict) -> str:
    action = str(step.get("action") or "wait")
    idx = step.get("element")
    if action in TYPING_ACTIONS and isinstance(idx, int) and 0 <= idx < len(elements):
        adb.tap(*elements[idx].center)
        time.sleep(0.5)
    if action == "tap":
        idx = step.get("element")
        if isinstance(idx, int) and 0 <= idx < len(elements):
            adb.tap(*elements[idx].center)
            return "ok"
        return "bad_element"
    if action == "tap_point":
        pt = step.get("point") or []
        if len(pt) == 2:
            adb.tap(int(pt[0] * size[0] / 1000), int(pt[1] * size[1] / 1000))
            return "ok"
        return "bad_point"
    if action == "type":
        adb.type_text(str(step.get("text") or ""))
        return "ok"
    if action == "type_secret":
        env = SECRET_FIELDS.get(str(step.get("field")))
        value = os.environ.get(env or "")
        if not value:
            return "missing_secret"
        adb.type_text(value)
        return "ok"
    if action == "sms_code":
        since = state.setdefault("sms_since", time.time() - 60)
        code = _wait_sms(since)
        if not code:
            return "sms_timeout"
        state["sms_since"] = time.time()
        adb.type_text(code)
        return "ok"
    if action in ("email_code", "email_link"):
        alias = os.environ.get(SECRET_FIELDS["app_email"])
        if not alias:
            return "missing_secret"
        since = state.setdefault("email_since", time.time() - 120)
        found = _wait_email(alias, since, action == "email_link")
        if not found:
            return "email_timeout"
        state["email_since"] = time.time()
        if action == "email_code":
            adb.type_text(found)
        else:
            adb.shell(f"am start -a android.intent.action.VIEW -d {shlex.quote(found)}")
        return "ok"
    if action == "totp_code":
        secret = os.environ.get(TOTP_ENV)
        if not secret:
            return "missing_secret"
        import pyotp

        adb.type_text(pyotp.TOTP(secret.replace(" ", "")).now())
        return "ok"
    if action == "swipe":
        adb.swipe(str(step.get("direction") or "up"))
        return "ok"
    if action == "back":
        adb.key("KEYCODE_BACK")
        return "ok"
    if action == "enter":
        adb.key("KEYCODE_ENTER")
        return "ok"
    if action == "wait":
        time.sleep(2)
        return "ok"
    return "terminal" if action in {"done", "fail"} else "unknown_action"


def run(task: str, package: str, *, apk_dir: Path | None = None, max_steps: int = 40,
        model: str | None = None, serial: str | None = None, run_dir: Path | None = None) -> dict:
    adb = Adb(serial)
    if apk_dir and not adb.has_package(package):
        apks = apks_in(apk_dir)
        if not apks:
            return {"ok": False, "reason": "no_apk"}
        print(adb.install(apks).strip()[-200:], flush=True)
    if not adb.has_package(package):
        return {"ok": False, "reason": "not_installed"}
    adb.launch(package)
    time.sleep(5)

    run_dir = run_dir or RUNS / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    client = _model_client()
    model = model or os.environ.get("MVP_ANDROID_MODEL", "gemini-2.5-flash")
    size = adb.size()
    history: list[dict] = []
    state: dict[str, Any] = {}
    outcome: dict[str, Any] = {"ok": False, "reason": "max_steps"}
    for n in range(1, max_steps + 1):
        png = adb.screencap()
        (run_dir / f"{n:02d}.png").write_bytes(png)
        elements = parse_ui(adb.ui_xml())
        step = decide(client, model, task, png, elements, history)
        result = execute(adb, step, elements, size, state)
        step.update(step=n, result=result, t=time.time())
        history.append(step)
        print(f"[{n:02d}] {step.get('action')} -> {result}: {step.get('reason', '')[:100]}", flush=True)
        if result == "terminal":
            outcome = {"ok": step["action"] == "done", "reason": step["action"], "summary": step.get("summary")}
            break
        time.sleep(1.5)
    (run_dir / "final.png").write_bytes(adb.screencap())
    outcome.update(steps=len(history), run_dir=str(run_dir))
    (run_dir / "trace.json").write_text(json.dumps({"task": task, "package": package, "outcome": outcome, "history": history}, indent=2))
    return outcome


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--package", required=True)
    ap.add_argument("--apk-dir", type=Path)
    ap.add_argument("--max-steps", type=int, default=40)
    ap.add_argument("--model")
    ap.add_argument("--serial")
    args = ap.parse_args()
    out = run(args.task, args.package, apk_dir=args.apk_dir, max_steps=args.max_steps,
              model=args.model, serial=args.serial)
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
