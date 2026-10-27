"""Calls to the gateway service (FETCHGATE_URL). Standard library only: agent scripts need nothing installed."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from fetchgate.gate import ApifyNotAllowed, remote_url
from fetchgate.ledger import BudgetExceeded, job_cap


def _call(path: str, body: dict[str, Any] | None = None, timeout: float = 1500.0) -> dict[str, Any]:
    req = urllib.request.Request(remote_url() + path, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error") or str(e)
        except ValueError:
            msg = str(e)
        if e.code == 402:
            raise BudgetExceeded(msg) from None
        if e.code == 403:
            raise ApifyNotAllowed(msg) from None
        if e.code == 400:
            raise ValueError(msg) from None
        raise RuntimeError(f"fetchgate service: HTTP {e.code}: {msg}") from None


def _common(job: str, max_cost_usd: float | None, allow_apify: bool,
            creds_override: dict[str, str] | None) -> dict[str, Any]:
    # The service clamps budget_usd to its own ceiling; FETCH_BUDGET_USD here can only ask.
    return {"job": job, "budget_usd": job_cap(max_cost_usd), "allow_apify": allow_apify,
            "creds": creds_override or None}


def fetch(url: str, *, browser: bool, scroll: bool, max_cost_usd: float | None, job: str, allow_apify: bool,
          routes: tuple[str, ...] | None, creds_override: dict[str, str] | None, capture: str | None,
          max_scrolls: int | None) -> dict[str, Any]:
    return _call("/fetch", {"url": url, "browser": browser, "scroll": scroll, "routes": list(routes) if routes else None,
                            "capture": capture, "max_scrolls": max_scrolls}
                 | _common(job, max_cost_usd, allow_apify, creds_override))


def run_actor(actor: str, payload: dict[str, Any], *, job: str, max_cost_usd: float | None, wait_s: float,
              estimate_usd: float, allow_apify: bool, creds_override: dict[str, str] | None,
              info: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    got = _call("/actor", {"actor": actor, "payload": payload, "wait_s": wait_s, "estimate_usd": estimate_usd}
                | _common(job, max_cost_usd, allow_apify, creds_override), timeout=wait_s + 300)
    if info is not None:
        info.update(got.get("run") or {})
    return got["items"]


def job_summary(job: str) -> dict[str, Any]:
    from urllib.parse import quote

    return _call("/jobs/" + quote(job, safe=""))


def health() -> dict[str, Any]:
    return _call("/health", timeout=10)

