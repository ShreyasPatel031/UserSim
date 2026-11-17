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
             "--remote-debugging-address=127.0.0.1", f"--user-data-dir={cls.tmp}", "about:blank"],
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


if __name__ == "__main__":
    unittest.main()
