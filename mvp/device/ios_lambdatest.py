"""iPhone backend on LambdaTest real devices (Appium/XCUITest), plus an agent loop that runs one test goal end to end
and returns the steps, findings and LambdaTest's session video.

    python -m mvp.device.ios_lambdatest upload  path/to/app.ipa              -> prints lt://APP...
    python -m mvp.device.ios_lambdatest run --app lt://APP... --goal-file goal.md --out runs/<name> [--device "iPhone 15"]

Credentials come from env (LT_USERNAME / LT_ACCESS_KEY, or the file in LT_ENV, default /root/.usersim/lambdatest.env);
nothing is logged or written to the output folder. The agent is Gemini on Vertex (GOOGLE_CLOUD_PROJECT).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import time
from typing import Any

import requests

from mvp.device.ios_browserstack import IOSDevice

HUB = "https://mobile-hub.lambdatest.com/wd/hub"
UPLOAD = "https://manual-api.lambdatest.com/app/upload/realDevice"
SESSIONS = "https://mobile-api.lambdatest.com/mobile-automation/api/v1/sessions"


def creds() -> tuple[str, str]:
    if not os.environ.get("LT_ACCESS_KEY"):
        path = os.environ.get("LT_ENV", "/root/.usersim/lambdatest.env")
        for line in open(path):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)
    return os.environ["LT_USERNAME"], os.environ["LT_ACCESS_KEY"]


def upload(ipa: str, name: str | None = None) -> str:
    with open(ipa, "rb") as f:
        r = requests.post(UPLOAD, auth=creds(), files={"appFile": f},
                          data={"name": name or os.path.basename(ipa)}, timeout=900)
    r.raise_for_status()
    return r.json()["app_url"]


class LTDevice(IOSDevice):
    def __init__(self, app: str, device: str = "iPhone 15", os_version: str = "17", name: str = "usersim-qa",
                 build: str = "usersim-qa"):
        from appium import webdriver
        from appium.options.ios import XCUITestOptions
        user, key = creds()
        opts = XCUITestOptions()
        opts.platform_name = "ios"
        opts.set_capability("lt:options", {
            "username": user, "accessKey": key, "w3c": True, "isRealMobile": True,
            "deviceName": device, "platformVersion": os_version, "platformName": "ios", "app": app,
            "build": build, "name": name, "video": True, "visual": True, "devicelog": True, "network": True,
            "autoAcceptAlerts": False, "idleTimeout": 600})
        opts.set_capability("appium:newCommandTimeout", 600)
        self.d = webdriver.Remote(HUB, options=opts)
        self.size = self.d.get_window_size()
        self.session_id = self.d.session_id


def session_info(session_id: str) -> dict[str, Any]:
    r = requests.get(f"{SESSIONS}/{session_id}", auth=creds(), timeout=60)
    return r.json() if r.ok else {"http": r.status_code}


AGENT_PROMPT = """You are a careful QA tester using a real iPhone app. Your goal and checklist:

{goal}

You see the current screenshot and a list of visible elements (type, label, centre x,y in points; screen {w}x{h}).
History of your last actions:
{history}

Reply with JSON only:
{{"thought": "what you see and why the next action", "action": {{"action": "tap"|"tap_label"|"type"|"swipe"|"wait"|"done",
  "x": int, "y": int, "label": str, "text": str, "direction": "up"|"down"|"left"|"right", "s": float}},
 "finding": null | {{"severity": "bug"|"confusing"|"ok", "checklist_item": str, "what_happened": str, "expected": str}}}}
Use "done" when every checklist item has been tried or you are blocked; say why in the thought. Report a finding whenever
something looks off, confusing or broken, and an "ok" finding when a checklist item works."""


def run(a) -> None:
    from google import genai
    from google.genai import types
    goal = open(a.goal_file).read()
    os.makedirs(f"{a.out}/shots", exist_ok=True)
    client = genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"],
                          location=os.environ.get("VERTEX_LOCATION", "us-central1"))
    t0 = time.time()
    dev = LTDevice(a.app, a.device, a.os_version, name=a.name, build=a.build)
    steps, findings, history = [], [], []
    try:
        for i in range(a.max_steps):
            obs = dev.observe()
            open(f"{a.out}/shots/{i:03d}.png", "wb").write(obs["screenshot_png"])
            prompt = AGENT_PROMPT.format(goal=goal, w=obs["size"]["width"], h=obs["size"]["height"],
                                         history="\n".join(history[-12:]) or "(none)")
            prompt += "\nElements:\n" + json.dumps(obs["elements"])
            resp = client.models.generate_content(
                model=a.model, contents=[types.Part.from_bytes(data=obs["screenshot_png"], mime_type="image/png"), prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2))
            try:
                dec = json.loads(resp.text)
            except Exception:
                dec = {"thought": "unparseable reply", "action": {"action": "wait", "s": 1}}
            act = dec.get("action") or {"action": "wait", "s": 1}
            if dec.get("finding"):
                findings.append({**dec["finding"], "step": i, "shot": f"shots/{i:03d}.png"})
            rec = {"step": i, "t": round(time.time() - t0, 1), "thought": dec.get("thought"), "action": act}
            if act.get("action") == "done":
                steps.append(rec)
                break
            try:
                dev.act(act)
                rec["result"] = "ok"
            except Exception as e:  # noqa: BLE001
                rec["result"] = f"error: {type(e).__name__}"
            steps.append(rec)
            history.append(f"{i}: {act} -> {rec['result']}")
            time.sleep(a.settle)
    finally:
        sid = dev.session_id
        dev.quit()
    time.sleep(10)
    info = session_info(sid)
    data = info.get("data") or {}
    report = {"app": a.app, "device": a.device, "os": a.os_version, "session_id": sid, "seconds": round(time.time() - t0),
              "steps": len(steps), "findings": findings,
              "video_url": data.get("video_url"), "session_url": data.get("public_url") or data.get("dashboard_url")}
    json.dump(steps, open(f"{a.out}/steps.json", "w"), indent=1)
    json.dump(report, open(f"{a.out}/report.json", "w"), indent=1)
    print(json.dumps({k: report[k] for k in ("session_id", "seconds", "steps", "video_url")}))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("upload"); u.add_argument("ipa"); u.add_argument("--name")
    r = sub.add_parser("run")
    r.add_argument("--app", required=True); r.add_argument("--goal-file", required=True); r.add_argument("--out", required=True)
    r.add_argument("--device", default="iPhone 15"); r.add_argument("--os-version", default="17")
    r.add_argument("--name", default="usersim-qa"); r.add_argument("--build", default="usersim-qa")
    r.add_argument("--model", default="gemini-2.5-flash"); r.add_argument("--max-steps", type=int, default=60)
    r.add_argument("--settle", type=float, default=1.0)
    a = ap.parse_args()
    if a.cmd == "upload":
        print(upload(a.ipa, a.name))
    else:
        run(a)


if __name__ == "__main__":
    main()
