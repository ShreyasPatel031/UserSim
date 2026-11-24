"""Pay-per-minute real iPhones on AWS Device Farm (remote access sessions).

Billing is $0.17 per device minute while a session runs (first 1,000 minutes free).
The device is wiped when the session ends, so sign in to the Apple ID each session.

Credentials: standard AWS env vars (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) or a
profile. The IAM user needs the `devicefarm:*` actions (AWSDeviceFarmFullAccess).
Device Farm only runs in us-west-2.

  python mvp/device/devicefarm.py devices            # iPhones available for remote access
  python mvp/device/devicefarm.py start [--device "Apple iPhone 15"] [--minutes 30]
  python mvp/device/devicefarm.py status [SESSION_ARN]
  python mvp/device/devicefarm.py stop [SESSION_ARN]   # always stop: billing runs until then
  python mvp/device/devicefarm.py demo [SESSION_ARN]   # drive the phone over Appium, save a screenshot

Programmatic control: each running session exposes an Appium URL at
endpoints.remoteDriverEndpoint (valid while the session runs, max 150 min).
"""
from __future__ import annotations

import argparse
import sys
import time

import boto3

REGION = "us-west-2"
PROJECT = "usersim-ios"


def client():
    return boto3.client("devicefarm", region_name=REGION)


def project_arn(c) -> str:
    for p in c.get_paginator("list_projects").paginate().build_full_result()["projects"]:
        if p["name"] == PROJECT:
            return p["arn"]
    return c.create_project(name=PROJECT)["project"]["arn"]


def ios_devices(c) -> list[dict]:
    filters = [
        {"attribute": "PLATFORM", "operator": "EQUALS", "values": ["IOS"]},
        {"attribute": "REMOTE_ACCESS_ENABLED", "operator": "EQUALS", "values": ["TRUE"]},
    ]
    out = [d for d in c.get_paginator("list_devices").paginate(filters=filters)
           .build_full_result()["devices"]
           if d.get("availability") in ("HIGHLY_AVAILABLE", "AVAILABLE")]
    return sorted(out, key=lambda d: (d.get("availability") != "HIGHLY_AVAILABLE", d["name"]))


def console_url(arn: str) -> str:
    # arn:aws:devicefarm:us-west-2:ACCT:session:PROJECT_ID/SESSION_ID/00000
    proj, sess = arn.split(":session:")[1].split("/")[:2]
    return (f"https://{REGION}.console.aws.amazon.com/devicefarm/home?region={REGION}"
            f"#/mobile/projects/{proj}/sessions/{sess}")


def latest_running(c) -> str | None:
    sess = c.list_remote_access_sessions(arn=project_arn(c))["remoteAccessSessions"]
    live = [s for s in sess if s["status"] not in ("COMPLETED", "STOPPING")]
    return live[0]["arn"] if live else None


def appium_url(c, arn: str) -> str:
    r = c.get_remote_access_session(arn=arn)["remoteAccessSession"]
    url = (r.get("endpoints") or {}).get("remoteDriverEndpoint")
    if not url:
        raise SystemExit(f"no Appium endpoint (status {r['status']})")
    return url


def demo(c, arn: str, out: str = "devicefarm_demo.png") -> int:
    from appium import webdriver
    from appium.options.ios import XCUITestOptions

    opts = XCUITestOptions()
    opts.platform_name = "iOS"
    opts.automation_name = "XCUITest"
    opts.bundle_id = "com.apple.mobilesafari"
    drv = webdriver.Remote(appium_url(c, arn), options=opts)
    try:
        print("window:", drv.get_window_size())
        drv.activate_app("com.apple.mobilesafari")
        time.sleep(3)
        drv.get_screenshot_as_file(out)
        print("screenshot:", out)
    finally:
        drv.quit()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices")
    s = sub.add_parser("start")
    s.add_argument("--device", default="", help="substring of the device name, e.g. 'iPhone 15'")
    s.add_argument("--minutes", type=int, default=30, help="hard timeout (caps the bill)")
    for name in ("status", "stop", "demo", "url"):
        sub.add_parser(name).add_argument("arn", nargs="?")
    a = ap.parse_args()
    c = client()

    if a.cmd == "devices":
        for d in ios_devices(c):
            print(f"{d['name']:<28} iOS {d['os']:<8} {d.get('availability','')}")
        return 0

    if a.cmd == "start":
        devs = [d for d in ios_devices(c) if a.device.lower() in d["name"].lower()]
        if not devs:
            print("no matching iPhone available for remote access", file=sys.stderr)
            return 1
        d = devs[0]
        proj = project_arn(c)
        # Device Farm timeouts are set per project (minutes).
        c.update_project(arn=proj, defaultJobTimeoutMinutes=a.minutes)
        r = c.create_remote_access_session(
            projectArn=proj, deviceArn=d["arn"], name="usersim",
            interactionMode="INTERACTIVE")["remoteAccessSession"]
        arn = r["arn"]
        print(f"starting {d['name']} iOS {d['os']} (timeout {a.minutes} min)")
        while True:
            r = c.get_remote_access_session(arn=arn)["remoteAccessSession"]
            if r["status"] in ("RUNNING", "COMPLETED"):
                break
            print("  status:", r["status"]); time.sleep(10)
        print("status:", r["status"], r.get("result", ""))
        print("open in browser:", console_url(arn))
        print("session arn:", arn)
        print("stop when done: python mvp/device/devicefarm.py stop")
        return 0

    arn = a.arn or latest_running(c)
    if not arn:
        print("no running session"); return 0
    if a.cmd == "url":  # Appium URL for mvp/device/ios_server.py
        print(appium_url(c, arn)); return 0
    if a.cmd == "demo":
        return demo(c, arn)
    if a.cmd == "status":
        r = c.get_remote_access_session(arn=arn)["remoteAccessSession"]
        print(r["status"], r.get("result", ""), r.get("deviceMinutes", {}))
        print(console_url(arn))
    else:
        c.stop_remote_access_session(arn=arn)
        print("stopping", arn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
