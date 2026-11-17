"""Saved signed-in accounts for the seed_vm backend.

Browserbase gave every user a residential IP and a built-in captcha solver; the seeds are GCP datacenter IPs with fresh
contexts, so signup walls (hCaptcha, reCAPTCHA scoring, disabled signup buttons) now stop many cells before the task
(Asana study 42a925dd, Nov 17). Most study tasks are not signups: those cells can start signed in.

One Playwright storage_state per registrable domain lives in the bucket at
    <MVP_SEED_STATES_PREFIX or DEFAULT_GCS/seed_states>/<domain>.json
as {"domain", "storage_state": {"cookies", "origins"}, "seed", "saved_at", "address", "source"}.
- Loaded into a cell's new context (sessions._open_browser) unless the task itself is a signup; the cell is routed to
  the seed that saved it when that seed has a free slot (same egress IP the site has seen).
- Saved back at finalize when the judge saw a signed-in app page, so the next cell and the next study reuse it.
- Seeded from the seeds' identity disks (site_states/ and Chrome profiles/) by scripts/vm/export_seed_states.py.
limits.json seed_saved_accounts=false turns all of it off.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any
from urllib.parse import urlsplit

CACHE_TTL_S = 300.0
_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}
_LOCK = threading.Lock()

# Tasks whose goal is creating the account must sign up for real (docs/E2E_TEST.md), never start signed in.
_SIGNUP_TASK_RE = re.compile(
    r"sign ?up|create (?:a |an |your |a new )?(?:new )?account|register|registration|verify your email", re.I)


def enabled() -> bool:
    from mvp.sim_mcp import limits

    return bool(limits.get("seed_saved_accounts"))


def domain_of(url_or_host: str) -> str:
    from mvp.sim_mcp.sessions import registrable_domain

    host = urlsplit(url_or_host).hostname if "://" in url_or_host else url_or_host
    return registrable_domain(host or "")


def prefix() -> str:
    from mvp.gcs_store import DEFAULT_GCS

    return (os.environ.get("MVP_SEED_STATES_PREFIX") or f"{DEFAULT_GCS}/seed_states").rstrip("/")


def uri(domain: str) -> str:
    return f"{prefix()}/{domain}.json"


def eligible(task: str) -> bool:
    """A cell may start signed in unless its task is the signup itself."""
    return not _SIGNUP_TASK_RE.search(task or "")


def live_cookies(state: dict[str, Any], domain: str, now: float | None = None) -> list[dict[str, Any]]:
    """Cookies for this site that have not expired (session cookies, expires -1, count as live)."""
    now = time.time() if now is None else now
    out = []
    for c in (state or {}).get("cookies") or []:
        cdom = str(c.get("domain") or "").lstrip(".").lower()
        if not (cdom == domain or cdom.endswith("." + domain)):
            continue
        exp = c.get("expires")
        if isinstance(exp, (int, float)) and exp > 0 and exp < now:
            continue
        out.append(c)
    return out


def usable(entry: dict[str, Any] | None, domain: str) -> bool:
    state = (entry or {}).get("storage_state")
    return isinstance(state, dict) and bool(live_cookies(state, domain))


def load(domain: str) -> dict[str, Any] | None:
    """The saved entry for this site, or None. Cached CACHE_TTL_S; a GCS error reads as no state."""
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(domain)
        if hit and now - hit[0] < CACHE_TTL_S:
            return hit[1]
    entry = None
    try:
        from mvp.gcs_store import gcs_download_json

        got = gcs_download_json(uri(domain))
        entry = got if isinstance(got, dict) and usable(got, domain) else None
    except Exception as exc:  # noqa: BLE001
        print(f"[site_states] load {domain} failed: {exc!r}"[:200], flush=True)
    with _LOCK:
        _CACHE[domain] = (now, entry)
    return entry


def save(domain: str, storage_state: dict[str, Any], *, seed: str, study_id: str = "", address: str = "",
         source: str = "study") -> bool:
    """Store a signed-in state for this site (newest wins). False when there is nothing worth saving or GCS fails."""
    if not isinstance(storage_state, dict) or not live_cookies(storage_state, domain):
        return False
    entry = {"domain": domain, "storage_state": storage_state, "seed": seed, "saved_at": time.time(),
             "study_id": study_id, "address": address, "source": source}
    try:
        from mvp.gcs_store import gcs_upload_json

        gcs_upload_json(uri(domain), entry)
    except Exception as exc:  # noqa: BLE001
        print(f"[site_states] save {domain} failed: {exc!r}"[:200], flush=True)
        return False
    with _LOCK:
        _CACHE[domain] = (time.time(), entry)
    return True


def seed_endpoint(seed: str, endpoints: list[str]) -> str:
    """The configured CDP endpoint of a seed named 'usersim-signup-seed-N' or 'seed-N' (port 19220+N), or ''."""
    m = re.search(r"(?:^|-)(\d+)$", seed or "")
    if not m:
        return ""
    port = 19220 + int(m.group(1))
    for e in endpoints:
        if urlsplit(e.split("#", 1)[0]).port == port:
            return e.split("#", 1)[0].rstrip("/")
    return ""
