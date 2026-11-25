"""Hold one LambdaTest iPhone session open and drive it by hand over localhost HTTP (for an operator or a coding agent).

    python -m mvp.device.lt_drive --app lt://APP... --out dir [--port 8765]
    curl localhost:8765/observe            -> saves dir/shots/NNN.png, prints the visible elements
    curl -d '{"action":"tap","x":1,"y":2}' localhost:8765/act
    curl localhost:8765/quit               -> ends the session, prints the video link

Login values: write {{EMAIL}} / {{PASSWORD}} in a text; the real values come from QA_LOGIN_ENV and are never echoed.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from mvp.device.ios_lambdatest import LTDevice, fill_secrets, session_info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--device", default="iPhone 15"); ap.add_argument("--os-version", default="17")
    ap.add_argument("--name", default="usersim-drive"); ap.add_argument("--build", default="usersim-drive")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    os.makedirs(f"{a.out}/shots", exist_ok=True)
    dev = LTDevice(a.app, a.device, a.os_version, name=a.name, build=a.build)
    log = open(f"{a.out}/actions.jsonl", "a")
    state = {"n": 0, "t0": time.time()}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def reply(self, obj, code=200):
            b = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            try:
                if self.path.startswith("/observe"):
                    obs = dev.observe()
                    path = f"{a.out}/shots/{state['n']:03d}.png"
                    open(path, "wb").write(obs["screenshot_png"]); state["n"] += 1
                    self.reply({"shot": path, "size": obs["size"], "elements": obs["elements"]})
                elif self.path.startswith("/quit"):
                    sid = dev.session_id; dev.quit(); time.sleep(10)
                    data = (session_info(sid).get("data") or {})
                    self.reply({"session_id": sid, "seconds": round(time.time() - state["t0"]),
                                "video_url": data.get("video_url")})
                    os._exit(0)
                else:
                    self.reply({"error": "unknown"}, 404)
            except Exception as e:  # noqa: BLE001
                self.reply({"error": f"{type(e).__name__}: {str(e)[:300]}"}, 500)

        def do_POST(self):
            act = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            try:
                res = dev.act(fill_secrets(act))
            except Exception as e:  # noqa: BLE001
                res = f"error: {type(e).__name__}: {str(e)[:300]}"
            log.write(json.dumps({"t": round(time.time() - state["t0"], 1), "action": act, "result": res}) + "\n"); log.flush()
            self.reply({"result": res})

    print(json.dumps({"ready": True, "session_id": dev.session_id}), flush=True)
    HTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
