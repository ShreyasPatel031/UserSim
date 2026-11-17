"""Deep health probe for a seed's Chromium over raw CDP.

`/json/version` answers even when Chromium is wedged (Nov 17, seed 0: after an IAP tunnel dropped, a half-open CDP
client stayed attached and every new page hung on navigation). This probe does what a simulated user's first step
does: a fresh browser context, a new page, a data: URL load, a JS evaluation; then it disposes the context.

Standalone (stdlib + websockets) so the seed's own watchdog can run it:
    python mvp/sim_mcp/seed_probe.py http://127.0.0.1:9222      # exit 0 = healthy
The engine calls probe() through the IAP tunnel before handing a seed slot to a user.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from typing import Any
from urllib.parse import urlsplit, urlunsplit

PROBE_HTML = "data:text/html,<title>usersim-ok</title>ok"


class ProbeFailed(RuntimeError):
    pass


class SeedMisconfigured(ProbeFailed):
    """Chromium runs chrome-extension:// service workers, which crash the engine's Playwright driver (restarting
    Chromium does not fix it; its flags do)."""


def ws_url_for(endpoint: str, timeout: float = 4.0) -> str:
    """Browser websocket URL for a CDP http endpoint, with host:port rewritten to the endpoint's (Chromium may report
    its own 127.0.0.1:9222, which is the far end of a tunnel)."""
    endpoint = endpoint.rstrip("/")
    with urllib.request.urlopen(endpoint + "/json/version", timeout=timeout) as resp:  # noqa: S310 (config URL)
        ws = json.loads(resp.read(20000).decode("utf-8"))["webSocketDebuggerUrl"]
    ep, w = urlsplit(endpoint), urlsplit(ws)
    return urlunsplit(("wss" if ep.scheme == "https" else "ws", ep.netloc, w.path, w.query, ""))


class _Cdp:
    def __init__(self, ws: Any, deadline: float) -> None:
        self.ws, self.deadline, self.n = ws, deadline, 0
        self.events: list[dict[str, Any]] = []

    def _recv(self) -> dict[str, Any]:
        left = self.deadline - time.time()
        if left <= 0:
            raise ProbeFailed("timed out")
        try:
            return json.loads(self.ws.recv(timeout=left))
        except TimeoutError as exc:
            raise ProbeFailed("timed out") from exc

    def call(self, method: str, params: dict[str, Any] | None = None, session: str | None = None) -> dict[str, Any]:
        self.n += 1
        msg: dict[str, Any] = {"id": self.n, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self.ws.send(json.dumps(msg))
        while True:
            got = self._recv()
            if got.get("id") == self.n:
                if "error" in got:
                    raise ProbeFailed(f"{method}: {got['error'].get('message', got['error'])}")
                return got.get("result") or {}
            if "method" in got:
                self.events.append(got)

    def wait_event(self, method: str, session: str) -> None:
        if any(e.get("method") == method and e.get("sessionId") == session for e in self.events):
            return
        while True:
            got = self._recv()
            if got.get("method") == method and got.get("sessionId") == session:
                return


def probe(endpoint: str, timeout: float = 5.0) -> str:
    """Raise ProbeFailed (or an OSError) unless a fresh context can load a page within `timeout` seconds.
    Returns the browser websocket URL (rewritten to the endpoint's host:port)."""
    from websockets.sync.client import connect

    ws_url = ws_url_for(endpoint, timeout=min(timeout, 4.0))
    deadline = time.time() + timeout
    with connect(ws_url, open_timeout=timeout, close_timeout=2, max_size=8 * 2**20) as ws:
        cdp = _Cdp(ws, deadline)
        # Chrome 159's own chrome-extension:// service workers crash Playwright's driver in
        # _CRBrowser._onAttachedToTarget on connect_over_cdp (Asana study 42a925dd, Nov 17). Chromium must run with
        # --disable-extensions --disable-component-extensions-with-background-pages (seed_cdp_chromium.sh).
        # Only extension workers count: product sites (Asana, ClickUp, ...) register their own service workers inside
        # users' contexts, and those must not mark a busy seed unhealthy mid-study.
        workers = [t.get("url", "") for t in cdp.call("Target.getTargets").get("targetInfos", [])
                   if t.get("type") == "service_worker" and str(t.get("url", "")).startswith("chrome-extension://")]
        if workers:
            raise SeedMisconfigured(f"{len(workers)} service_worker target(s) ({workers[0][:80]}); start Chromium with "
                                    "--disable-extensions --disable-component-extensions-with-background-pages")
        ctx = cdp.call("Target.createBrowserContext", {"disposeOnDetach": True})["browserContextId"]
        try:
            target = cdp.call("Target.createTarget", {"url": "about:blank", "browserContextId": ctx})["targetId"]
            sess = cdp.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
            cdp.call("Page.enable", session=sess)
            nav = cdp.call("Page.navigate", {"url": PROBE_HTML}, session=sess)
            if nav.get("errorText"):
                raise ProbeFailed(f"navigate: {nav['errorText']}")
            cdp.wait_event("Page.loadEventFired", sess)
            title = cdp.call("Runtime.evaluate", {"expression": "document.title", "returnByValue": True},
                             session=sess).get("result", {}).get("value")
            if title != "usersim-ok":
                raise ProbeFailed(f"page did not render (title {title!r})")
        finally:
            try:
                cdp.deadline = max(cdp.deadline, time.time() + 2)
                cdp.call("Target.disposeBrowserContext", {"browserContextId": ctx})
            except Exception:  # noqa: BLE001
                pass
    return ws_url


def main(argv: list[str]) -> int:
    endpoint = argv[1] if len(argv) > 1 else "http://127.0.0.1:9222"
    t0 = time.time()
    try:
        probe(endpoint, timeout=float(argv[2]) if len(argv) > 2 else 5.0)
    except SeedMisconfigured as exc:
        print(f"MISCONFIGURED {endpoint}: {exc}"[:300])
        return 2  # the watchdog must not restart-loop on this
    except Exception as exc:  # noqa: BLE001
        print(f"UNHEALTHY {endpoint}: {exc!r}"[:300])
        return 1
    print(f"OK {endpoint} {int((time.time() - t0) * 1000)} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
