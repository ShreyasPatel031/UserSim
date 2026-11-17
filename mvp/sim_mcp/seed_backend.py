"""Seed-VM browser backend for the MCP engine (replaces Browserbase).

Each signup seed (usersim-signup-seed-N, scripts/vm/create_signup_seed.sh) keeps one headed Chromium under Xvfb
with CDP bound to the seed's own 127.0.0.1:9222 (scripts/vm/usersim-seed-cdp.service). Nothing on the seed listens
on a public port: the MCP server reaches each seed through an IAP SSH tunnel (mvp/deploy/usersim-seed-tunnel@.service,
local port 19220+N). The seeds' traffic leaves from their reserved static egress IP.

Two engines (limits.json browser_engine, default "camoufox", Shreyas Nov 17: "always run camoufox"):
  camoufox  a Camoufox (Firefox) Playwright server on the seed's 127.0.0.1:9333 (scripts/vm/seed_camoufox_server.py,
            one fixed fingerprint per seed), tunnel port 19320+N, endpoint ws://127.0.0.1:1932N/usersim,
            connected with playwright.firefox.connect. Client and server Playwright versions must match (1.62).
  chromium  the seed Chromium over CDP (127.0.0.1:9222, tunnel 19220+N, http://127.0.0.1:1922N), connect_over_cdp.
The endpoint's scheme says which: ws:// = Camoufox, http:// = Chromium CDP.

One simulated user = one isolated browser context on a seed. A seed carries ``seed_sessions_per_seed`` contexts; the
rest of the callers wait up to ``seed_wait_s`` for a slot and are then told to retry (the cell stays queued).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

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
    def engine(self) -> str:
        return engine_of(self.endpoint)

    @property
    def seed_label(self) -> str:
        n = seed_index(self.endpoint)
        return f"seed-{n}" if n >= 0 else self.endpoint


PORT_BASES = {"chromium": 19220, "camoufox": 19320}


def engine_of(endpoint: str) -> str:
    return "camoufox" if urlsplit(endpoint).scheme in ("ws", "wss") else "chromium"


def seed_index(endpoint: str) -> int:
    """Seed N from the tunnel port (19220+N for Chromium, 19320+N for Camoufox), or -1."""
    port = urlsplit(endpoint).port or 0
    for base in PORT_BASES.values():
        if base <= port < base + 80:
            return port - base
    return -1


def browser_engine() -> str:
    from mvp.sim_mcp import limits

    return "chromium" if str(limits.get("browser_engine") or "").strip().lower() == "chromium" else "camoufox"


_LOCK = threading.Condition()
_IN_USE: dict[str, int] = {}
_HEALTH: dict[str, tuple[float, str]] = {}  # endpoint -> (checked_at, ws_url or "")
HEALTH_TTL_S = 20.0


def blocked_host(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS)


_CAPS: dict[str, int] = {}  # endpoint -> its own cap from a "url#N" entry


def _limits() -> tuple[list[str], int, float]:
    """Endpoints of the active engine, default per-seed cap, wait. An entry "...:19220#3" caps that seed at 3."""
    from mvp.sim_mcp import limits

    key = "seed_camoufox_endpoints" if browser_engine() == "camoufox" else "seed_cdp_endpoints"
    eps: list[str] = []
    for raw in limits.get(key) or []:
        url, _, n = raw.strip().partition("#")
        url = url.rstrip("/")
        if not url:
            continue
        eps.append(url)
        if n.strip().isdigit() and int(n) > 0:
            _CAPS[url] = int(n)
        else:
            _CAPS.pop(url, None)
    return eps, max(1, int(limits.get("seed_sessions_per_seed"))), float(limits.get("seed_wait_s"))


def endpoints() -> list[str]:
    """The active engine's configured endpoints (without '#N')."""
    return _limits()[0]


def cap_of(endpoint: str, default: int) -> int:
    return _CAPS.get(endpoint, default)


def ws_url_for(endpoint: str, timeout: float = 4.0) -> str:
    from mvp.sim_mcp.seed_probe import ws_url_for as _ws

    return _ws(endpoint, timeout=timeout)


def probe_ws(endpoint: str, timeout: float = 5.0) -> str:
    """Deep probe (fresh context loads a page) and the browser websocket URL. Raises if the seed is down or wedged:
    /json/version alone answers even when every new page hangs (Nov 17, seed 0)."""
    from mvp.sim_mcp.seed_probe import probe

    return probe(endpoint, timeout=timeout)


def _healthy(endpoint: str) -> str:
    now = time.time()
    at, ws = _HEALTH.get(endpoint, (0.0, ""))
    if now - at < HEALTH_TTL_S:
        return ws
    try:
        ws = probe_ws(endpoint)
    except Exception as exc:  # noqa: BLE001
        print(f"[seed] {endpoint} unhealthy: {exc!r}"[:200], flush=True)
        ws = ""
    _HEALTH[endpoint] = (now, ws)
    return ws


def mark_unhealthy(endpoint: str) -> None:
    """A session just failed to open on this seed: probe it again before the next user goes there."""
    _HEALTH.pop(endpoint, None)


def acquire(wait_s: float | None = None, prefer: str = "") -> SeedSlot:
    """Reserve a slot on the least-loaded healthy seed, waiting up to wait_s for one to free up. prefer: the endpoint
    of the seed that saved this site's signed-in state (same egress IP the site knows); used when it has a free slot,
    otherwise any seed (the cookies travel with the state)."""
    eps, cap, default_wait = _limits()
    if not eps:
        raise NoSeeds(f"no {browser_engine()} seed endpoints configured")
    deadline = time.time() + (default_wait if wait_s is None else wait_s)
    while True:
        healthy = [(e, ws) for e in eps if (ws := _healthy(e))]
        with _LOCK:
            free = [(e, ws) for e, ws in healthy if _IN_USE.get(e, 0) < cap_of(e, cap)]
            if free:
                mine = [x for x in free if prefer and x[0] == prefer.rstrip("/")]
                e, ws = mine[0] if mine else min(free, key=lambda x: _IN_USE.get(x[0], 0) / cap_of(x[0], cap))
                _IN_USE[e] = _IN_USE.get(e, 0) + 1
                return SeedSlot(endpoint=e, ws_url=ws)
            left = deadline - time.time()
            if left <= 0:
                if not healthy:
                    raise NoSeeds(f"no seed browser answered on CDP ({len(eps)} configured)")
                raise SeedsBusy(f"all {len(healthy)} seed(s) are full")
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
        "seeds": [{"endpoint": e, "healthy": bool(_HEALTH.get(e, (0, ""))[1]), "in_use": used.get(e, 0),
                   "cap": cap_of(e, cap)} for e in eps],
        "per_seed": cap,
    }
