"""Routes for /ph and /try (additive; mounted by mvp.server)."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()
STATIC = Path(__file__).resolve().parents[1] / "static"
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _client_ip(request: Request) -> str:
    """Rate-limit key. On Vercel the platform sets x-vercel-forwarded-for / x-real-ip (clients cannot spoof them);
    elsewhere use the socket peer. IPv6 is keyed per /64 so one allocation can't rotate addresses past the caps."""
    import ipaddress
    import os

    raw = ""
    if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
        raw = (request.headers.get("x-vercel-forwarded-for") or request.headers.get("x-real-ip") or "").split(",")[0]
    raw = raw.strip() or (request.client.host if request.client else "unknown")
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return raw
    if ip.version == 6:
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


async def _body(request: Request) -> dict:
    try:
        j = await request.json()
    except Exception:  # noqa: BLE001
        j = None
    if not isinstance(j, dict):
        raise HTTPException(400, "Send a JSON object.")
    return j


def _json(data, max_age: int = 60) -> JSONResponse:
    return JSONResponse(data, headers={"Cache-Control": f"public, max-age={max_age}"})


@router.get("/ph")
async def ph_page() -> FileResponse:
    return FileResponse(STATIC / "ph.html")


@router.get("/try")
async def try_page() -> FileResponse:
    return FileResponse(STATIC / "try.html")


def _data_down(exc: Exception) -> JSONResponse:
    print(f"[ph] data read failed: {exc!r}", flush=True)   # detail stays in server logs, never in the browser
    return JSONResponse({"error": "forecast data is unavailable right now"}, status_code=503,
                        headers={"Cache-Control": "no-store"})


@router.get("/api/ph/today")
async def ph_today(day: str | None = None):
    try:
        return await _ph_today(day)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        return _data_down(exc)


async def _ph_today(day: str | None):
    from mvp.ph_site import live

    if day and not DAY.match(day):
        raise HTTPException(400, "day must be YYYY-MM-DD")
    days = await asyncio.to_thread(live.available_days)
    today = live.today_pt()
    if today not in days:
        days = [today] + days            # today always exists: its board comes live from Product Hunt's API
    # Never show another day's picks under today's date: no day given means today, forecasts or not.
    d = day if day in days else today
    view = await asyncio.to_thread(live.day_view, d)
    view["days"] = days
    try:
        view["accuracy"] = await asyncio.to_thread(live.accuracy)
    except Exception:  # noqa: BLE001 - the accuracy line is optional
        view["accuracy"] = {}
    return _json(view, 60)


@router.api_route("/api/ph/cron/snapshot", methods=["GET", "POST"])
async def ph_cron_snapshot(request: Request):
    """Scheduler entry point (every 15 min on the clock PT, and 23:50 PT): append this slot's leaderboard snapshot.
    Needs `Authorization: Bearer <CRON_SECRET>` (Vercel Cron sends exactly this)."""
    import hmac
    import os

    from mvp.ph_site import ph_live

    secret = os.environ.get("CRON_SECRET", "")
    if len(secret) < 16:
        return JSONResponse({"error": "CRON_SECRET is not set on this server"}, status_code=503)
    if not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {secret}"):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        return JSONResponse(await asyncio.to_thread(ph_live.append_slot), headers={"Cache-Control": "no-store"})
    except Exception as exc:  # noqa: BLE001
        print(f"[ph_live] cron failed: {exc!r}", flush=True)
        return JSONResponse({"error": "snapshot failed", "kind": type(exc).__name__}, status_code=500)


@router.get("/api/ph/health")
async def ph_health():
    """Which data reads work on this deployment and how long they take (no secrets, no data values)."""
    import os
    import time

    from mvp.ph_site import gcs, live

    def probe():
        out = {}
        for name, fn in (("list_days", live.available_days),
                         ("scoreboard", lambda: bool(gcs.read_json("results/web/scoreboard.json", ttl=0))),
                         ("forecast_0005", lambda: bool(live.forecasts(live.available_days()[0]))),
                         ("person_index", lambda: gcs.read_bytes("site/person_index_v1.npz", ttl=0) is not None)):
            t = time.time()
            try:
                v = fn()
                out[name] = {"ok": bool(v), "ms": int((time.time() - t) * 1000)}
            except Exception as exc:  # noqa: BLE001
                out[name] = {"ok": False, "ms": int((time.time() - t) * 1000), "error": type(exc).__name__}
        return out

    checks = await asyncio.to_thread(probe)
    from mvp.ph_site import ph_live
    try:
        await asyncio.to_thread(lambda: ph_live.board(live.today_pt()))  # refreshes it if older than a minute
    except Exception:  # noqa: BLE001 - reported through health() below
        pass
    lb = await asyncio.to_thread(ph_live.health)
    checks["live_board"] = {"ok": bool(lb["configured"] and lb["age_s"] is not None and lb["age_s"] < 600), "ms": 0,
                            **{k: lb[k] for k in ("configured", "age_s", "launches", "last_ok_at", "last_error", "last_error_at")}}
    ts = await asyncio.to_thread(ph_live.ts_health, live.today_pt())
    checks["live_record"] = {"ok": "error" not in ts, "ms": 0, **ts}
    try:                                   # /try needs its code and numpy to import on this server
        from mvp.ph_site import person_e5, try_sim  # noqa: F401
        checks["try_imports"] = {"ok": True, "ms": 0}
    except Exception as exc:  # noqa: BLE001
        checks["try_imports"] = {"ok": False, "ms": 0, "error": type(exc).__name__}
    return JSONResponse({"ok": all(c["ok"] for c in checks.values()), "checks": checks,
                         "try_configured": len(os.environ.get("TRY_SIGNING_KEY", "")) >= 32,
                         "on_vercel": bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))},
                        headers={"Cache-Control": "no-store"})


@router.get("/api/ph/weekly")
async def ph_weekly():
    from mvp.ph_site import live

    try:
        return _json(await asyncio.to_thread(live.weekly) or {}, 300)
    except Exception as exc:  # noqa: BLE001
        return _data_down(exc)


def _err(exc: Exception) -> JSONResponse:
    from mvp.ph_site.safe_fetch import FetchError

    from mvp.ph_site.try_sim import BadToken, NotConfigured

    if isinstance(exc, NotConfigured):
        return JSONResponse({"error": str(exc)}, status_code=503)
    if isinstance(exc, BadToken):
        return JSONResponse({"error": str(exc)}, status_code=403)
    if isinstance(exc, PermissionError):
        return JSONResponse({"error": str(exc)}, status_code=429)
    if isinstance(exc, (FetchError, ValueError)):
        return JSONResponse({"error": str(exc)}, status_code=422)
    print(f"[try] error {exc!r}", flush=True)
    return JSONResponse({"error": "Something went wrong on our side. Try again in a minute."}, status_code=500)


def _load_try():
    """Import the simulator; a missing dependency is a clean 503, never a raw server error."""
    try:
        from mvp.ph_site import try_sim
        return try_sim
    except ImportError as exc:
        print(f"[try] import failed: {exc!r}", flush=True)
        raise HTTPException(503, "The simulator is unavailable on this server right now.") from None


@router.post("/api/try/page")
async def try_page_step(request: Request):
    try_sim = _load_try()
    body = await _body(request)
    url = str(body.get("url") or "")[:2000]
    try:
        return JSONResponse(await asyncio.wait_for(try_sim.step_page(url, _client_ip(request)), timeout=45))
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Reading the page took too long."}, status_code=504)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/api/try/text")
async def try_text_step(request: Request):
    try_sim = _load_try()
    body = await _body(request)
    try:
        return JSONResponse(await asyncio.wait_for(try_sim.step_text(
            str(body.get("name") or "")[:200], str(body.get("tagline") or "")[:300],
            str(body.get("description") or "")[:4000], _client_ip(request)), timeout=45))
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Reading the description took too long."}, status_code=504)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/api/try/{step}")
async def try_step(step: str, request: Request):
    try_sim = _load_try()
    body = await _body(request)
    tok = str(body.get("token") or "")[:2000]
    try:
        if step == "people":
            return JSONResponse(await asyncio.wait_for(try_sim.step_people(tok), timeout=30))
        if step == "launch":
            return JSONResponse(await asyncio.to_thread(try_sim.step_launch, tok))
        if step == "reactions":
            return JSONResponse(await asyncio.wait_for(try_sim.step_reactions(tok), timeout=45))
        if step == "asks":
            return JSONResponse(await asyncio.wait_for(try_sim.step_asks(tok), timeout=50))
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
    raise HTTPException(404, "unknown step")
