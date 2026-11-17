"""Live (local Chromium + a fake app): a saved state that still signs in vs one that does not.

app.example.test is mapped to a local server that redirects to /login unless the 'sid=good' cookie is sent. Covers
scripts/check_saved_states.check_one and the engine's signed-out heuristic. Skipped without Playwright Chromium."""

from __future__ import annotations

import asyncio
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mvp.test_sim_mcp_seed_live import _chrome  # noqa: E402


class App(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        cookie = self.headers.get("Cookie") or ""
        if self.path.startswith("/login"):
            body = b"<title>Log in</title><input type=password>"
        elif "sid=good" in cookie:
            body = (b"<title>Workspace</title><button aria-label='Account menu'><img alt='avatar'></button>"
                    b"<h1>Your projects</h1><a href='/logout' hidden>Log out</a>")
        elif "sid=plain" in cookie:  # not a login page, but nothing that says signed in (a landing page)
            body = b"<title>Welcome</title><h1>The best way to plan projects</h1><a>Get started</a>"
        else:
            self.send_response(302)
            self.send_header("Location", "/login?next=/")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _entry(value: str) -> dict:
    exp = time.time() + 3600
    return {"seed": "usersim-signup-seed-0", "saved_at": 1,
            "storage_state": {"cookies": [{"name": "sid", "value": value, "domain": "app.example.test", "path": "/",
                                           "expires": exp, "httpOnly": False, "secure": False, "sameSite": "Lax"}],
                              "origins": [{"origin": "http://app.example.test", "localStorage": [{"name": "k", "value": "v"}]}]}}


@unittest.skipUnless(_chrome(), "no Playwright Chromium")
class CheckSavedStatesLive(unittest.TestCase):
    def test_live_and_dead(self):
        import check_saved_states as C
        from mvp.sim_mcp import site_states as SS
        from playwright.async_api import async_playwright

        srv = HTTPServer(("127.0.0.1", 0), App)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        port = srv.server_address[1]
        orig = SS.app_url_for
        # the fake app is plain http on a random port
        SS.app_url_for = lambda e, d: (orig(e, d).replace("https://", "http://").rstrip("/") + f":{port}/"
                                       if orig(e, d) else "")
        self.addCleanup(setattr, SS, "app_url_for", orig)

        async def run():
            async with async_playwright() as pw:
                b = await pw.chromium.launch(headless=True, executable_path=_chrome(),
                                             args=C.FLAGS + [f"--host-resolver-rules=MAP *.example.test 127.0.0.1"])
                try:
                    live = await C.check_one(b, "example.test", _entry("good"))
                    dead = await C.check_one(b, "example.test", _entry("expired"))
                    unsure = await C.check_one(b, "example.test", _entry("plain"))
                    none = await C.check_one(b, "example.test", {"storage_state": {"cookies": [], "origins": []}})
                finally:
                    await b.close()
                return live, dead, none, unsure

        live, dead, none, unsure = asyncio.run(run())
        self.assertEqual(unsure["verdict"], "UNSURE", unsure)
        self.assertEqual(live["verdict"], "LIVE", live)
        self.assertEqual(dead["verdict"], "DEAD", dead)
        self.assertIn("/login", dead["landed"])
        self.assertEqual(none["verdict"], "NO_APP_URL")


if __name__ == "__main__":
    unittest.main()
