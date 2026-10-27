"""fetch(): the one function every web fetch goes through.

Routes, cheapest first (prices in docs/discovery/FETCH_LADDER.md):
  page mode     vm -> vm_camoufox -> residential -> residential_camoufox -> apify_unblocker
  browser mode  vm_camoufox -> residential_camoufox -> residential_chromium -> apify_residential_camoufox
                (also scroll=True)
The first route that gets the real page (HTTP 200, not a bot challenge) wins; a route a site walled off is skipped
for that site for a while (ladder.BLOCK_TTL_S): at once on the VM's own IP, after WALLS_TO_BLOCK walls in a row on
the rotating residential / Apify IPs (one exit IP's 403 says little about the next). Apify routes run only when every other route of the mode was tried
(or is known blocked / has no credentials) for this URL without a page, AND Apify is allowed (ALLOW_APIFY=1).

Each attempt is logged with its route, bytes and estimated $ (ledger), and a job stops with BudgetExceeded before
an attempt that would take it past its cap. When FETCHGATE_URL is set (agent scripts on the VM), the call goes to
the gateway service there, which holds the credentials; otherwise it runs here with what this process can read.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any

from fetchgate import creds, ladder
from fetchgate.ledger import BudgetExceeded, default_job, job_cap, ledger

PAGE_ROUTES = ("vm", "vm_camoufox", "residential", "residential_camoufox", "apify_unblocker")
BROWSER_ROUTES = ("vm_camoufox", "residential_camoufox", "residential_chromium", "apify_residential_camoufox")
APIFY_ROUTES = frozenset({"apify_unblocker", "apify_residential_camoufox"})
RESIDENTIAL_ROUTES = frozenset({"residential", "residential_camoufox", "residential_chromium"})
WALLS_TO_BLOCK = {"vm": 1, "vm_camoufox": 1}  # other routes rotate their exit IP: 3 walls in a row
_WALLS: dict[tuple[str, str], int] = {}
# Worst-case $ one attempt can cost, reserved against the budget before it runs (measured costs replace these).
ESTIMATE_USD = {"vm": 0.0, "vm_camoufox": 0.0, "residential": 0.0005, "residential_camoufox": 0.004, "residential_chromium": 0.004,
                "apify_unblocker": ladder.UNBLOCKER_USD_PER_PAGE, "apify_residential_camoufox": 0.03}
SCROLL_ESTIMATE_USD = {"residential_camoufox": 0.05, "residential_chromium": 0.05, "apify_residential_camoufox": 0.4}
FINAL_STATUSES = frozenset({404, 410})  # the site says the page does not exist: dearer routes would say the same
BROWSER_TIMEOUT_S = 180.0
SCROLL_TIMEOUT_S = 1200.0


class ApifyNotAllowed(RuntimeError):
    """An Apify route or actor was asked for without ALLOW_APIFY=1."""


def apify_allowed(flag: bool | None = None) -> bool:
    return (os.environ.get("ALLOW_APIFY", "").strip() == "1") if flag is None else bool(flag)


def remote_url() -> str:
    """The gateway service to call ('' = run in this process). The service itself never forwards."""
    if os.environ.get("FETCHGATE_SERVICE") == "1":
        return ""
    return (os.environ.get("FETCHGATE_URL") or "").strip().rstrip("/")


def fetch(url: str, *, browser: bool = False, scroll: bool = False, max_cost_usd: float | None = None,
          job: str | None = None, allow_apify: bool | None = None, routes: tuple[str, ...] | None = None,
          creds_override: dict[str, str] | None = None, capture: str | None = None,
          max_scrolls: int | None = None) -> dict[str, Any]:
    """The page by the cheapest route that gets it.

    Returns {url, status, route, final_url, html, bytes, usd, job, job_usd, attempts} (+ scrolls and responses in
    browser / scroll mode); route '' when no route got the real page. A 404 / 410 ends the ladder (status 404, route
    set): the site has no such page. Raises BudgetExceeded when the job's cap (or
    the daily cap) would be passed. routes= can only narrow the ladder (e.g. ("vm",) for free routes only); Apify
    routes then never run, since they need every cheaper route tried first."""
    job = job or default_job()
    if remote_url():
        from fetchgate import client

        return client.fetch(url, browser=browser, scroll=scroll, max_cost_usd=max_cost_usd, job=job,
                            allow_apify=apify_allowed(allow_apify), routes=routes, creds_override=creds_override,
                            capture=capture, max_scrolls=max_scrolls)
    return run_ladder(url, browser=browser or scroll, scroll=scroll, cap=job_cap(max_cost_usd), job=job,
                      allow_apify=apify_allowed(allow_apify), routes=routes, creds_override=creds_override,
                      capture=capture, max_scrolls=max_scrolls)


def run_ladder(url: str, *, browser: bool, scroll: bool, cap: float, job: str, allow_apify: bool,
               routes: tuple[str, ...] | None = None, creds_override: dict[str, str] | None = None,
               capture: str | None = None, max_scrolls: int | None = None) -> dict[str, Any]:
    if not re.match(r"^https?://", url or ""):
        raise ValueError(f"not an http(s) URL: {url!r}")
    mode = "scroll" if scroll else "browser" if browser else "page"
    ladder_routes = BROWSER_ROUTES if browser else PAGE_ROUTES
    residential = creds.residential(creds_override)
    token = creds.apify_token(creds_override) if allow_apify else ""
    site = ladder._site(url)
    led = ledger()
    out: dict[str, Any] = {"url": url, "status": 0, "route": "", "final_url": "", "html": "", "bytes": 0, "usd": 0.0,
                           "job": job, "mode": mode, "attempts": []}
    cheaper_all_failed = True  # every non-Apify route of this mode ran without the page, or hit this site's wall lately
    for route in ladder_routes:
        if routes is not None and route not in routes:
            cheaper_all_failed = cheaper_all_failed and route in APIFY_ROUTES
            out["attempts"].append({"route": route, "skipped": "not in routes="})
            continue
        if route in APIFY_ROUTES:
            why = ("ALLOW_APIFY is not set" if not allow_apify else
                   "the cheaper routes were not all tried for this URL" if not cheaper_all_failed else
                   "no Apify token available to the gateway" if not token else "")
            if why:
                out["attempts"].append({"route": route, "skipped": why})
                continue
        with ladder._BLOCKED_LOCK:
            if time.time() - ladder._BLOCKED.get((site, route), 0) < ladder.BLOCK_TTL_S:
                out["attempts"].append({"route": route, "skipped": f"bot wall on {site} recently"})
                continue
        if route in RESIDENTIAL_ROUTES and not residential:
            cheaper_all_failed = False  # not tried: Apify must not stand in for a missing residential proxy
            out["attempts"].append({"route": route, "skipped": "no residential proxy available to the gateway"})
            continue
        estimate = (SCROLL_ESTIMATE_USD.get(route) if scroll else None) or ESTIMATE_USD.get(route, 0.0)
        led.reserve(job, estimate, cap)  # BudgetExceeded stops the job here
        t, meter, row = time.time(), {"bytes": 0}, {"route": route}
        got: dict[str, Any] | None = None
        try:
            got = _attempt(route, url, residential, token, browser=browser, scroll=scroll, meter=meter,
                           job=job, cap=cap, reserved=estimate, capture=capture, max_scrolls=max_scrolls)
        except Exception as exc:  # noqa: BLE001 - next route; timeouts and errors never mark a route blocked
            row["error"] = creds.redact(repr(exc), residential, token)[:200]
        ok = bool(got) and ladder.is_clean(got["status"], got["html"])
        usd = ladder.tier_cost(route, meter.get("bytes", 0), ok=ok)
        row |= {"bytes": meter.get("bytes", 0), "usd": round(usd, 6), "ms": int((time.time() - t) * 1000)}
        if got:
            row |= {"status": got["status"], "kb": round(len(got["html"]) / 1024), "pass": ok,
                    "challenge": ladder._summary(got["status"], got["html"], t)["challenge"]}
        logged = led.record({"job": job, "url": url, "route": route, "mode": mode, "status": row.get("status", 0),
                             "ok": ok, "bytes": row["bytes"], "usd": row["usd"], "ms": row["ms"],
                             "error": row.get("error"), "scrolls": (got or {}).get("scrolls")}, reserved=estimate)
        out["attempts"].append(row)
        out["bytes"] += row["bytes"]
        out["usd"] = round(out["usd"] + row["usd"], 6)
        out["job_usd"] = logged["job_usd"]
        if got:
            out |= {k: v for k, v in got.items() if k not in ("bytes",)}
        if ok or (got and got["status"] in FINAL_STATUSES and not row.get("challenge")):
            with ladder._BLOCKED_LOCK:
                _WALLS.pop((site, route), None)
            out["route"] = route  # the real page, or the site's own definite answer that it has none
            return out
        if row.get("challenge") and row.get("status") != 429:  # a bot wall (not a rate limit, timeout or 404):
            with ladder._BLOCKED_LOCK:  # don't knock on it again for a while
                _WALLS[(site, route)] = _WALLS.get((site, route), 0) + 1
                if _WALLS[(site, route)] >= WALLS_TO_BLOCK.get(route, 3):
                    ladder._BLOCKED[(site, route)] = time.time()
                    _WALLS.pop((site, route), None)
    out["job_usd"] = round(led.spent(job), 6)
    return out


def _attempt(route: str, url: str, residential: str, token: str, *, browser: bool, scroll: bool,
             meter: dict[str, Any], job: str, cap: float, reserved: float, capture: str | None,
             max_scrolls: int | None) -> dict[str, Any]:
    if not browser:
        status, html = ladder.tier_fetch(route, url, residential or None, meter=meter, apify_token=token or None)
        return {"status": status, "html": html, "final_url": meter.get("final_url") or url}
    from fetchgate import browser as B

    proxy = (ladder.us_exit(residential) if route in ("residential_camoufox", "residential_chromium") else
             ladder.apify_proxy("RESIDENTIAL", token=token) if route == "apify_residential_camoufox" else None)
    led = ledger()

    def over(nbytes: int) -> bool:
        """Stop scrolling once this attempt's measured cost would take the job past its cap."""
        cost = ladder.tier_cost(route, nbytes)
        return cost > reserved and led.spent(job) + cost > cap

    engine = "chromium" if route.endswith("_chromium") else "camoufox"
    if engine == "camoufox" and not ladder.ensure_tool("camoufox")["ok"]:
        raise RuntimeError(f"camoufox unavailable: {ladder.ensure_tool('camoufox')['how'][-120:]}")
    box: dict[str, Any] = {}

    def work() -> None:
        try:
            kw: dict[str, Any] = {"scroll": scroll, "meter": meter, "stop": over, "capture": capture, "engine": engine}
            if max_scrolls:
                kw["max_scrolls"] = max_scrolls
            box["r"] = B.load(url, proxy, **kw)
        except Exception as exc:  # noqa: BLE001 - re-raised below
            box["e"] = exc
    with ladder._BROWSERS:  # own thread: a browser that failed leaves an event loop behind in its thread
        th = threading.Thread(target=work, daemon=True)
        th.start()
        th.join(SCROLL_TIMEOUT_S if scroll else BROWSER_TIMEOUT_S)
    if "e" in box:
        raise box["e"]
    if "r" not in box:
        raise TimeoutError(f"browser: no page in {SCROLL_TIMEOUT_S if scroll else BROWSER_TIMEOUT_S:.0f} s")
    return box["r"]


def probe(url: str, *, kind: str = "ladder", browsers: bool = True, allow_apify: bool | None = None,
          creds_override: dict[str, str] | None = None, job: str | None = None) -> dict[str, Any]:
    """The diagnostic probes behind POST /api/discovery/probe, with their costs logged under `job`.
    kind: ladder (every route), saved (residential proxy, all methods), own_unblocker, apify_unblocker,
    apify_residential (Apify kinds and the ladder's Apify route need ALLOW_APIFY=1)."""
    allow = apify_allowed(allow_apify)
    residential = creds.residential(creds_override)
    led = ledger()
    job = job or f"probe-{time.strftime('%Y-%m-%d')}"
    if kind == "ladder":
        tiers = ladder.TIERS if allow else tuple(t for t in ladder.TIERS if t not in APIFY_ROUTES)
        est = sum(ESTIMATE_USD.get(t, 0) for t in tiers)
        led.reserve(job, est, job_cap())
        out = ladder.ladder_probe(url, residential or None, tiers=tiers,
                                  apify_token=creds.apify_token(creds_override) if allow else None)
        for tier, r in out["routes"].items():
            led.record({"job": job, "url": url, "route": tier, "mode": "probe", "status": r.get("status", 0),
                        "ok": bool(r.get("pass")), "bytes": int(r.get("wire_kb", 0)) * 1024,
                        "usd": r.get("usd_per_page", 0.0), "error": r.get("error")})
        led.record({"job": job, "url": url, "route": "", "mode": "probe", "usd": 0}, reserved=est)
        return out
    if kind in ("apify_unblocker", "apify_residential"):
        if not allow:
            raise ApifyNotAllowed("Apify probes need ALLOW_APIFY=1")
        proxy = ladder.apify_proxy("UNBLOCKER" if kind == "apify_unblocker" else "RESIDENTIAL",
                                   token=creds.apify_token(creds_override))
    elif kind == "own_unblocker":
        if not residential:
            raise ValueError("no residential proxy available to the gateway")
        led.reserve(job, 0.05, job_cap())
        got = ladder.own_unblock(url, residential)
        led.record({"job": job, "url": url, "route": "own_unblocker", "mode": "probe", "ok": got["ok"],
                    "usd": 0.0, "note": "CapSolver and residential bytes not metered"}, reserved=0.05)
        return {"url": url, "proxy_kind": kind, "ok": got["ok"], "steps": got["steps"],
                "final": ladder._summary(got["status"], got["html"], time.time()) if got["ok"] else None}
    else:
        proxy = residential or None
    led.reserve(job, 0.05, job_cap())
    out = ladder.probe(url, proxy, browsers=browsers) | {"proxy_kind": kind}
    led.record({"job": job, "url": url, "route": f"probe:{kind}", "mode": "probe", "ok": True, "usd": 0.0,
                "note": "per-method bytes not metered; held $0.05"}, reserved=0.05)
    return out


def sample(url: str, *, allow_apify: bool | None = None, creds_override: dict[str, str] | None = None,
           job: str | None = None) -> dict[str, Any]:
    """One page's HTML for writing a parser against the real page (POST /api/discovery/sample): the ladder."""
    got = fetch(url, job=job or f"sample-{time.strftime('%Y-%m-%d')}", allow_apify=allow_apify, creds_override=creds_override)
    return {"status": got["status"], "html": got["html"], "route": got["route"], "usd": got["usd"]}


__all__ = ["fetch", "probe", "sample", "BudgetExceeded", "ApifyNotAllowed", "PAGE_ROUTES", "BROWSER_ROUTES"]
