"""Seed-VM browser backend for the MCP engine (replaces Browserbase).

Each signup seed (usersim-signup-seed-N, scripts/vm/create_signup_seed.sh) keeps one headed Chromium under Xvfb
with CDP bound to the seed's own 127.0.0.1:9222 (scripts/vm/usersim-seed-cdp.service). Nothing on the seed listens
on a public port: the MCP server reaches each seed through an IAP SSH tunnel (mvp/deploy/usersim-seed-tunnel@.service,
local port 19220+N). The seeds' traffic leaves from their reserved static egress IP.

One simulated user = one isolated browser context on a seed. A seed carries ``seed_sessions_per_seed`` contexts; the
rest of the callers wait up to ``seed_wait_s`` for a slot and are then told to retry (the cell stays queued).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# Sites these browsers must never load (the seeds' IPs are shared with nothing that may touch them).
BLOCKED_HOSTS = ("producthunt.com",)


class SeedsBusy(RuntimeError):
    """Every healthy seed is at its session cap."""


class NoSeeds(RuntimeError):
    """No seed answered on CDP."""


@dataclass
class SeedSlot:
    endpoint: str
    ws_url: str
    id: str = field(default_factory=lambda: "seed-" + uuid.uuid4().hex[:12])
    backend: str = "seed_vm"
    connect_url: str = ""
    session_url: str | None = None
    released: bool = False

    def __post_init__(self) -> None:
        self.connect_url = self.ws_url

    @property
    def seed_label(self) -> str:
        port = urlsplit(self.endpoint).port or 0
        return f"seed-{port - 19220}" if 19220 <= port < 19300 else self.endpoint


_LOCK = threading.Condition()
_IN_USE: dict[str, int] = {}
_HEALTH: dict[str, tuple[float, str]] = {}  # endpoint -> (checked_at, ws_url or "")
HEALTH_TTL_S = 20.0


def blocked_host(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS)


def _limits() -> tuple[list[str], int, float]:
    from mvp.sim_mcp import limits

    eps = [e.rstrip("/") for e in (limits.get("seed_cdp_endpoints") or []) if e.strip()]
    return eps, max(1, int(limits.get("seed_sessions_per_seed"))), float(limits.get("seed_wait_s"))


def ws_url_for(endpoint: str, timeout: float = 4.0) -> str:
    """Browser websocket URL for a CDP http endpoint, with host:port rewritten to the endpoint's (Chromium reports
    its own 127.0.0.1:9222, which is the far end of the tunnel)."""
    with urllib.request.urlopen(endpoint + "/json/version", timeout=timeout) as resp:  # noqa: S310 (config URL)
        ws = json.loads(resp.read(20000).decode("utf-8"))["webSocketDebuggerUrl"]
    ep, w = urlsplit(endpoint), urlsplit(ws)
    return urlunsplit(("wss" if ep.scheme == "https" else "ws", ep.netloc, w.path, w.query, ""))


def _healthy(endpoint: str) -> str:
    now = time.time()
    at, ws = _HEALTH.get(endpoint, (0.0, ""))
    if now - at < HEALTH_TTL_S:
        return ws
    try:
        ws = ws_url_for(endpoint)
    except Exception as exc:  # noqa: BLE001
        print(f"[seed] {endpoint} unhealthy: {exc!r}"[:200], flush=True)
        ws = ""
    _HEALTH[endpoint] = (now, ws)
    return ws


def acquire(wait_s: float | None = None) -> SeedSlot:
    """Reserve a slot on the least-loaded healthy seed, waiting up to wait_s for one to free up."""
    eps, cap, default_wait = _limits()
    if not eps:
        raise NoSeeds("no seed_cdp_endpoints configured")
    deadline = time.time() + (default_wait if wait_s is None else wait_s)
    while True:
        healthy = [(e, ws) for e in eps if (ws := _healthy(e))]
        with _LOCK:
            free = [(e, ws) for e, ws in healthy if _IN_USE.get(e, 0) < cap]
            if free:
                e, ws = min(free, key=lambda x: _IN_USE.get(x[0], 0))
                _IN_USE[e] = _IN_USE.get(e, 0) + 1
                return SeedSlot(endpoint=e, ws_url=ws)
            left = deadline - time.time()
            if left <= 0:
                if not healthy:
                    raise NoSeeds(f"no seed browser answered on CDP ({len(eps)} configured)")
                raise SeedsBusy(f"all {len(healthy)} seed(s) are at {cap} simulated users")
            _LOCK.wait(timeout=min(left, 3.0))


def release(slot: Any) -> None:
    if not isinstance(slot, SeedSlot) or slot.released:
        return
    slot.released = True
    with _LOCK:
        _IN_USE[slot.endpoint] = max(0, _IN_USE.get(slot.endpoint, 0) - 1)
        _LOCK.notify_all()


def status(probe: bool = False) -> dict[str, Any]:
    eps, cap, _ = _limits()
    if probe:
        for e in eps:
            _healthy(e)
    with _LOCK:
        used = dict(_IN_USE)
    return {
        "seeds": [{"endpoint": e, "healthy": bool(_HEALTH.get(e, (0, ""))[1]), "in_use": used.get(e, 0)} for e in eps],
        "per_seed": cap,
    }
