"""Verify the phone -> ntfy -> agent SMS path, and set it up.

Why this exists: a seed VM has no access to the owner's Messages database, so
SMS verification has to reach it another way. The handset forwards every
incoming SMS to an ntfy topic; the agent polls that topic. Nothing in the path
depends on a Mac being awake.

The part that cannot be automated from here is the forwarding rule on the phone.
Run this, text yourself, and confirm the code is extracted correctly.

    python scripts/local/sms_relay_check.py                 # watch for 120s
    python scripts/local/sms_relay_check.py --setup         # print phone setup
    python scripts/local/sms_relay_check.py --simulate      # fake an SMS

Phone setup (one time):

  iOS — Shortcuts app > Automation > New > Message
    Trigger:  "When I get a message"  (leave sender/content unfiltered)
              turn OFF "Ask Before Running"
    Action:   Get Contents of URL
              URL     https://ntfy.sh/<TOPIC>
              Method  POST
              Body    the message content (Shortcut Input)
              Headers Title: SMS
                      Authorization: Bearer <TOKEN>   (only if using a token)

  Android — install an SMS-forwarding app (SMS Forwarder, MacroDroid, Tasker)
    Rule:     on SMS received -> HTTP POST
              URL   https://ntfy.sh/<TOPIC>
              Body  %sms_body   (or the app's message variable)

Security: on public ntfy.sh the topic name is the only secret, and real
verification codes flow through it. Prefer a reserved topic with a token, or a
self-hosted ntfy. Set the token as push.ntfy_token in secrets/credentials.json
or MVP_NTFY_TOKEN, and this tool will use it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mvp.credentials import push_sms_topic  # noqa: E402
from mvp.sms_provider import _ntfy_base, _ntfy_headers, _sms_code, status  # noqa: E402


def print_setup(topic: str) -> None:
    token_set = bool(_ntfy_headers())
    print(__doc__.split("Phone setup (one time):")[1].replace("<TOPIC>", topic))
    if not token_set:
        print(
            "  NOTE: no ntfy token configured. The topic name is currently the only\n"
            "        thing protecting your SMS codes. Omit the Authorization header.\n"
        )


def watch(topic: str, seconds: float) -> int:
    url = f"{_ntfy_base()}/{topic}/json"
    started = time.time()
    seen: set[str] = set()
    found = 0
    print(f"watching {url} for {seconds:.0f}s — send yourself an SMS now\n")
    while time.time() - started < seconds:
        try:
            resp = httpx.get(
                url,
                params={"poll": "1", "since": str(int(started - 5))},
                headers=_ntfy_headers(),
                timeout=20.0,
            )
            if resp.status_code >= 300:
                print(f"  ntfy returned HTTP {resp.status_code}: {resp.text[:200]}")
                time.sleep(3)
                continue
            for line in resp.text.splitlines():
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("event") != "message":
                    continue
                mid = str(msg.get("id") or "")
                if mid in seen:
                    continue
                seen.add(mid)
                title = str(msg.get("title") or "")
                body = str(msg.get("message") or "")
                code = _sms_code(title, body)
                found += 1
                stamp = time.strftime("%H:%M:%S", time.localtime(msg.get("time") or 0))
                print(f"  [{stamp}] title={title!r}")
                print(f"            body={body[:120]!r}")
                print(f"            extracted code -> {code!r}")
                if code is None:
                    print(
                        "            NO CODE FOUND — paste this message to have the\n"
                        "            extractor adjusted."
                    )
        except Exception as exc:  # noqa: BLE001
            print(f"  poll error: {type(exc).__name__}: {exc}")
        time.sleep(3)

    print()
    if found:
        print(f"received {found} message(s) — the relay path works")
        return 0
    print(
        "no messages arrived.\n"
        "  - is the forwarding rule enabled on the phone?\n"
        "  - does it POST to exactly this topic?\n"
        "  - run with --setup to see the rule, or --simulate to test this side only"
    )
    return 1


def simulate(topic: str) -> int:
    body = "Your Todoist verification code is 481902. Do not share it."
    resp = httpx.post(
        f"{_ntfy_base()}/{topic}",
        content=body.encode(),
        headers={"Title": "SMS from 22395", **_ntfy_headers()},
        timeout=20.0,
    )
    print(f"published simulated SMS: HTTP {resp.status_code}")
    print(f"  body: {body}")
    print(f"  extractor reads: {_sms_code('SMS from 22395', body)!r} (expect '481902')")
    return 0 if resp.status_code < 300 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--setup", action="store_true", help="print phone-side setup")
    ap.add_argument("--simulate", action="store_true", help="publish a fake SMS")
    args = ap.parse_args()

    topic = push_sms_topic()
    if not topic:
        print(
            "No SMS topic. Set push.ntfy_topic in secrets/credentials.json "
            "(the SMS topic defaults to '<ntfy_topic>-sms'), or MVP_NTFY_SMS_TOPIC.",
            file=sys.stderr,
        )
        return 2

    print(f"topic:   {topic}")
    print(f"backend: {json.dumps(status())}\n")

    if args.setup:
        print_setup(topic)
        return 0
    if args.simulate:
        return simulate(topic)
    return watch(topic, args.seconds)


if __name__ == "__main__":
    sys.exit(main())
