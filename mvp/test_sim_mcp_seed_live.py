"""Live checks of the seed probe against a real local Chromium (skipped when no Playwright Chromium is installed)."""

from __future__ import annotations

import glob
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest

from mvp.sim_mcp import seed_probe


def _chrome() -> str:
    for pat in ("/opt/pw-browsers/chromium-*/chrome-linux*/chrome",
                os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return ""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(_chrome(), "no Playwright Chromium")
class SeedProbeLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.port = _free_port()
        cls.proc = subprocess.Popen(
            [_chrome(), "--headless=new", "--no-sandbox", f"--remote-debugging-port={cls.port}",
             "--remote-debugging-address=127.0.0.1", f"--user-data-dir={cls.tmp}",
             # same as scripts/vm/seed_cdp_chromium.sh: no extension service workers (they crash Playwright's driver)
             "--disable-extensions", "--disable-component-extensions-with-background-pages", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.ep = f"http://127.0.0.1:{cls.port}"
        for _ in range(100):
            try:
                seed_probe.ws_url_for(cls.ep, timeout=1)
                return
            except Exception:  # noqa: BLE001
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.kill()
        cls.proc.wait()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_healthy(self):
        self.assertTrue(seed_probe.probe(self.ep).startswith(f"ws://127.0.0.1:{self.port}/devtools/browser/"))

    def test_wedged_by_silent_auto_attach_client(self):
        # Nov 17 seed 0: a half-open CDP client (dropped tunnel) with auto-attach + waitForDebuggerOnStart holds
        # every new page. /json/version still answers; the deep probe must not.
        from websockets.sync.client import connect

        with connect(seed_probe.ws_url_for(self.ep)) as ws:
            ws.send(json.dumps({"id": 1, "method": "Target.setAutoAttach",
                                "params": {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}}))
            ws.recv(timeout=5)
            seed_probe.ws_url_for(self.ep)  # still answers
            with self.assertRaises(seed_probe.ProbeFailed):
                seed_probe.probe(self.ep, timeout=3)
        seed_probe.probe(self.ep)  # client gone -> healthy again


    def test_service_worker_target_fails_the_probe(self):
        # Nov 17 (Asana 42a925dd): a service_worker target crashed the engine's Playwright driver. A page in the
        # default context registers one here; the probe must report the seed as misconfigured.
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        from websockets.sync.client import connect

        class H(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body, ctype = ((b"self.addEventListener('fetch', () => {});", "text/javascript") if self.path == "/sw.js"
                               else (b"<script>navigator.serviceWorker.register('/sw.js')</script>", "text/html"))
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        def call(ws, n, method, params=None):
            ws.send(json.dumps({"id": n, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(ws.recv(timeout=10))
                if msg.get("id") == n:
                    return msg.get("result") or {}

        with connect(seed_probe.ws_url_for(self.ep)) as ws:
            # its own context, disposed at the end, so the worker does not outlive this test
            ctx = call(ws, 10, "Target.createBrowserContext")["browserContextId"]
            self.addCleanup(lambda: seed_probe.probe(self.ep))  # healthy again afterwards
            call(ws, 1, "Target.createTarget", {"url": f"http://127.0.0.1:{srv.server_address[1]}/", "browserContextId": ctx})
            try:
                for i in range(50):
                    infos = call(ws, 100 + i, "Target.getTargets")["targetInfos"]
                    if any(t["type"] == "service_worker" for t in infos):
                        break
                    time.sleep(0.1)
                else:
                    self.skipTest("this Chromium did not start a service worker")
                with self.assertRaises(seed_probe.SeedMisconfigured):
                    seed_probe.probe(self.ep)
                self.assertEqual(seed_probe.main(["x", self.ep]), 2)
            finally:
                call(ws, 3, "Target.disposeBrowserContext", {"browserContextId": ctx})


if __name__ == "__main__":
    unittest.main()
