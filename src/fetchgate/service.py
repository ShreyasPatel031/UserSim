"""The gateway as a localhost HTTP service. On the VM it runs as the `fetchgate` system user, the only user that can
read the proxy and Apify credentials (/etc/fetchgate/credentials.env, mode 600); agent scripts call it through
fetchgate.fetch() with FETCHGATE_URL=http://127.0.0.1:8765 and never see a credential.

  GET  /health         which routes have credentials (never the values), caps, log path
  GET  /jobs/<job>     route mix, pages, bytes and $ for one job
  POST /fetch          {url, browser?, scroll?, job?, budget_usd?, max_cost_usd?, allow_apify?, routes?, capture?,
                        max_scrolls?, creds?}  -> fetch() result
  POST /actor          {actor, payload, job?, budget_usd?, wait_s?, estimate_usd?, allow_apify?, creds?} -> {items}

The caller's job cap (its FETCH_BUDGET_USD) is clamped to FETCHGATE_MAX_JOB_USD here, and Apify runs only when the
caller set ALLOW_APIFY=1 and this service allows it (FETCHGATE_APIFY, default 1). Budget stops answer 402,
Apify refusals 403. Listens on 127.0.0.1 only.

    python -m fetchgate serve            # FETCHGATE_PORT, default 8765
"""

from __future__ import annotations

import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote

from fetchgate import creds, ledger as L
from fetchgate.gate import ApifyNotAllowed, run_ladder

DEFAULT_PORT = 8765


def max_job_usd() -> float:
    return L._num("FETCHGATE_MAX_JOB_USD", 50.0)


def service_allows_apify() -> bool:
    return os.environ.get("FETCHGATE_APIFY", "1").strip() != "0"


def _cap(body: dict[str, Any]) -> float:
    asked = body.get("budget_usd")
    asked = L.DEFAULT_JOB_USD if asked is None else float(asked)
    if body.get("max_cost_usd") is not None:
        asked = min(asked, float(body["max_cost_usd"]))
    return max(0.0, min(asked, max_job_usd()))


def _overrides(body: dict[str, Any]) -> dict[str, str] | None:
    """Keys a /discovery user supplied for their own run; only the fetch credential names are taken."""
    given = body.get("creds") or {}
    return {k: str(v) for k, v in given.items() if k in creds.NAMES and v} or None


def handle(path: str, body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
    """One request -> (HTTP status, JSON). Separate from the HTTP plumbing so tests can call it."""
    led = L.ledger()
    if body is None:
        if path == "/health":
            return 200, {"ok": True, "residential": bool(creds.residential()), "apify": bool(creds.apify_token()),
                         "apify_allowed_by_service": service_allows_apify(), "max_job_usd": max_job_usd(),
                         "daily_cap_usd": L.daily_cap(), "today_usd": round(led.today(), 6), "log": str(led.path)}
        if path.startswith("/jobs/"):
            return 200, led.summary(unquote(path[len("/jobs/"):]))
        return 404, {"error": "not found"}
    job = str(body.get("job") or L.default_job())
    allow = bool(body.get("allow_apify")) and service_allows_apify()
    try:
        if path == "/fetch":
            routes = tuple(body["routes"]) if body.get("routes") else None
            return 200, run_ladder(str(body.get("url") or ""), browser=bool(body.get("browser") or body.get("scroll")),
                                   scroll=bool(body.get("scroll")), cap=_cap(body), job=job, allow_apify=allow,
                                   routes=routes, creds_override=_overrides(body), capture=body.get("capture"),
                                   max_scrolls=body.get("max_scrolls"))
        if path == "/actor":
            from fetchgate import apify

            run: dict[str, Any] = {}
            items = apify._run(str(body["actor"]), body.get("payload") or {}, job=job, cap=_cap(body),
                               wait_s=float(body.get("wait_s") or 300), allow_apify=allow,
                               estimate_usd=float(body.get("estimate_usd") or apify.DEFAULT_ESTIMATE_USD),
                               creds_override=_overrides(body), info=run)
            return 200, {"items": items, "run": run}
    except L.BudgetExceeded as exc:
        return 402, {"error": str(exc), "kind": "budget"}
    except ApifyNotAllowed as exc:
        return 403, {"error": str(exc), "kind": "apify_not_allowed"}
    except (ValueError, KeyError, TypeError) as exc:
        return 400, {"error": creds.redact(repr(exc))[:300]}
    except Exception as exc:  # noqa: BLE001 - reported to the caller, never with credentials
        traceback.print_exc()
        return 500, {"error": creds.redact(repr(exc), creds.residential(), creds.apify_token())[:300]}
    return 404, {"error": "not found"}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, data: dict[str, Any]) -> None:
        raw = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        self._send(*handle(self.path, None))

    def do_POST(self) -> None:  # noqa: N802
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            self._send(400, {"error": "body must be JSON"})
            return
        self._send(*handle(self.path, body if isinstance(body, dict) else {}))

    def log_message(self, fmt: str, *args: Any) -> None:  # one line per request on stdout (journald)
        print(f"[fetchgate] {self.address_string()} {fmt % args}", flush=True)


def serve(port: int | None = None) -> None:
    os.environ["FETCHGATE_SERVICE"] = "1"  # never forward to ourselves
    port = port or int(os.environ.get("FETCHGATE_PORT") or DEFAULT_PORT)
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    srv.daemon_threads = True
    print(f"[fetchgate] listening on 127.0.0.1:{port}, log {L.ledger().path}", flush=True)
    srv.serve_forever()
