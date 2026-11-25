"""Hand-driven real-iPhone sessions on LambdaTest: the QA agent (Claude in the session) looks at each screenshot and
decides every action itself. No model sits in this loop.

Start one device server per variation (each holds its own LambdaTest session, so variations run on separate phones):

    python -m mvp.client_qa.drive serve --app lt://APP... --port 8801 --out mvp/client_qa/private/runs/<build>/<var> \
        --name "ENG-814 A build 4244" --build reframe-4244 [--device "iPhone 15" --os 17]

Then drive it (each command prints a compact element list and saves a screenshot under <out>/shots/):

    python -m mvp.client_qa.drive 8801 look [tag]
    python -m mvp.client_qa.drive 8801 tap X Y | label "Text" | type "text" | swipe up|down|left|right | back | wait S
    python -m mvp.client_qa.drive 8801 note ITEM pass|fail|blocked|confusing "what happened" ["expected"]
    python -m mvp.client_qa.drive 8801 quit          -> closes the session, writes session.json with the video link

Every action and note is appended to <out>/log.jsonl with a timestamp and the screenshot it was taken on, so
mvp.client_qa.report can build the per-checklist report. Credentials: LT_USERNAME / LT_ACCESS_KEY (dummy values are
fine where the proxy injects the real ones); nothing secret is written to disk.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

NOISE = ("scroll bar", "Screen Recording", "Key '")


def _shrink(png: bytes, width: int = 430) -> bytes:
    """Smaller copy for the agent to read (full-size kept for the report)."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(png))
        if im.width > width:
            im = im.resize((width, int(im.height * width / im.width)))
        b = io.BytesIO(); im.convert("RGB").save(b, "JPEG", quality=70)
        return b.getvalue()
    except Exception:  # noqa: BLE001
        return png


def serve(a) -> None:
    os.environ.setdefault("LT_USERNAME", "proxy-injected")
    os.environ.setdefault("LT_ACCESS_KEY", "proxy-injected")
    from mvp.device.ios_lambdatest import LTDevice, session_info
    os.makedirs(f"{a.out}/shots", exist_ok=True)
    t0 = time.time()
    # The plan has one device slot: a session request waits in LambdaTest's queue and the proxy may cut the long
    # request ("upstream request failed"). Keep asking until a phone is free.
    while True:
        try:
            dev = LTDevice(a.app, a.device, a.os, name=a.name, build=a.build)
            break
        except Exception as e:  # noqa: BLE001
            if time.time() - t0 > a.queue_max:
                raise
            print(f"waiting for a device: {repr(e)[:120]}", flush=True)
            time.sleep(20)
    log = open(f"{a.out}/log.jsonl", "a")
    state = {"n": 0, "last": None}
    meta = {"session_id": dev.session_id, "app": a.app, "device": a.device, "os": a.os, "name": a.name,
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)),
            "connect_s": round(time.time() - t0, 1)}
    json.dump(meta, open(f"{a.out}/session.json", "w"), indent=1)
    print(json.dumps(meta), flush=True)

    def write(rec):
        rec["t"] = round(time.time() - t0, 1)
        log.write(json.dumps(rec) + "\n"); log.flush()

    def look(tag):
        o = dev.observe()
        state["n"] += 1
        p = f"{a.out}/shots/{state['n']:03d}_{tag}.png"
        open(p, "wb").write(o["screenshot_png"])
        small = p[:-4] + ".small.jpg"
        open(small, "wb").write(_shrink(o["screenshot_png"]))
        state["last"] = os.path.relpath(p, a.out)
        els = [e for e in o["elements"] if not any(k in e["label"] for k in NOISE)]
        write({"kind": "look", "shot": state["last"]})
        return {"shot": small, "size": o["size"], "elements": els}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
            try:
                if self.path == "/look":
                    r = look(body.get("tag", "obs"))
                elif self.path == "/act":
                    act = body
                    if act["action"] == "back":
                        dev.d.back(); res = "ok"
                    else:
                        res = dev.act(act)
                    write({"kind": "act", "action": act, "result": res, "on": state["last"]})
                    time.sleep(float(body.get("settle", 1.5)))
                    r = look(body.get("tag", act["action"]))
                elif self.path == "/note":
                    write({"kind": "note", **body, "shot": state["last"]})
                    r = {"noted": body.get("item")}
                elif self.path == "/quit":
                    sid = dev.session_id
                    dev.quit()
                    time.sleep(8)
                    info = (session_info(sid).get("data") or {})
                    meta.update({"seconds": round(time.time() - t0), "video_url": info.get("video_url"),
                                 "session_url": info.get("public_url") or info.get("dashboard_url")})
                    json.dump(meta, open(f"{a.out}/session.json", "w"), indent=1)
                    r = meta
                else:
                    r = {"err": "path"}
            except Exception as e:  # noqa: BLE001
                write({"kind": "error", "path": self.path, "body": body, "err": repr(e)[:300]})
                r = {"err": repr(e)[:300]}
            b = json.dumps(r).encode()
            self.send_response(200); self.send_header("content-length", str(len(b))); self.end_headers()
            self.wfile.write(b)
            if self.path == "/quit":
                os._exit(0)

    HTTPServer(("127.0.0.1", a.port), H).serve_forever()


def call(port: int, path: str, body: dict) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=300).read())


def show(r: dict) -> None:
    if "elements" not in r:
        print(json.dumps(r)); return
    print(f"shot {r['shot']}  screen {r['size']['width']}x{r['size']['height']}")
    for e in r["elements"]:
        print(f"  {e['type'][:12]:12} {e['x']:4},{e['y']:<4} {e['label']}")


def cli(argv: list[str]) -> None:
    port, cmd, rest = int(argv[0]), argv[1], argv[2:]
    if cmd == "look":
        show(call(port, "/look", {"tag": rest[0] if rest else "look"}))
    elif cmd == "tap":
        show(call(port, "/act", {"action": "tap", "x": int(rest[0]), "y": int(rest[1])}))
    elif cmd == "label":
        show(call(port, "/act", {"action": "tap_label", "label": rest[0]}))
    elif cmd == "type":
        show(call(port, "/act", {"action": "type", "text": os.path.expandvars(rest[0]), "tag": "type"}))
    elif cmd == "swipe":
        show(call(port, "/act", {"action": "swipe", "direction": rest[0]}))
    elif cmd == "back":
        show(call(port, "/act", {"action": "back"}))
    elif cmd == "wait":
        show(call(port, "/act", {"action": "wait", "s": float(rest[0]) if rest else 3, "settle": 0}))
    elif cmd == "note":
        item, status, what = rest[0], rest[1], rest[2]
        print(call(port, "/note", {"item": item, "status": status, "what": what,
                                   "expected": rest[3] if len(rest) > 3 else ""}))
    elif cmd == "quit":
        print(json.dumps(call(port, "/quit", {})))
    else:
        sys.exit(f"unknown command {cmd}")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument("serve"); ap.add_argument("--app", required=True); ap.add_argument("--port", type=int, required=True)
        ap.add_argument("--out", required=True); ap.add_argument("--name", default="client-qa")
        ap.add_argument("--build", default="client-qa"); ap.add_argument("--device", default="iPhone 15")
        ap.add_argument("--os", default="17"); ap.add_argument("--queue-max", type=float, default=3600)
        serve(ap.parse_args())
    else:
        cli(sys.argv[1:])


if __name__ == "__main__":
    main()
