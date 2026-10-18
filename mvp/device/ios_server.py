"""Tiny local HTTP server holding one IOSDevice session (for agent/driver loops).
POST /observe -> json {elements,size,shot}; POST /act json -> ok. Screenshots saved to OUT dir."""
import json, os, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from mvp.device.ios_browserstack import IOSDevice

OUT = os.environ.get("IOS_OUT", "/workspace/product/ios-test/shots")
os.makedirs(OUT, exist_ok=True)
dev = IOSDevice(sys.argv[1], os.environ.get("IOS_DEVICE", "iPhone 15"), os.environ.get("IOS_OS", "17"))
print("session", dev.d.session_id, flush=True)
n = [0]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        try:
            if self.path == "/observe":
                o = dev.observe(); n[0] += 1
                p = f"{OUT}/{n[0]:03d}_{body.get('tag','obs')}.png"
                open(p, "wb").write(o["screenshot_png"])
                r = {"shot": p, "elements": o["elements"], "size": o["size"]}
            elif self.path == "/act":
                r = {"r": dev.act(body)}
            elif self.path == "/quit":
                dev.quit(); r = {"r": "bye"}
            else:
                r = {"err": "path"}
        except Exception as e:
            r = {"err": repr(e)[:500]}
        b = json.dumps(r).encode()
        self.send_response(200); self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)

HTTPServer(("127.0.0.1", 8799), H).serve_forever()
