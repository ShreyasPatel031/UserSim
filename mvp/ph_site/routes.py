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


@router.get("/api/ph/today")
async def ph_today(day: str | None = None):
    from mvp.ph_site import live

    if day and not DAY.match(day):
        raise HTTPException(400, "day must be YYYY-MM-DD")
    days = await asyncio.to_thread(live.available_days)
    if not days:
        raise HTTPException(503, "no forecasts yet")
    d = day if day in days else days[0]
    view = await asyncio.to_thread(live.day_view, d)
    view["days"] = days
    return _json(view, 60)


@router.get("/api/ph/track-record")
async def ph_track():
    from mvp.ph_site import live

    return _json(await asyncio.to_thread(live.track_record), 300)


@router.get("/api/ph/weekly")
async def ph_weekly():
    from mvp.ph_site import live

    return _json(await asyncio.to_thread(live.weekly) or {}, 300)


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


@router.post("/api/try/page")
async def try_page_step(request: Request):
    from mvp.ph_site import try_sim

    body = await _body(request)
    url = str(body.get("url") or "")[:2000]
    try:
        return JSONResponse(await asyncio.wait_for(try_sim.step_page(url, _client_ip(request)), timeout=45))
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Reading the page took too long."}, status_code=504)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@router.post("/api/try/{step}")
async def try_step(step: str, request: Request):
    from mvp.ph_site import try_sim

    body = await _body(request)
    tok = str(body.get("token") or "")[:2000]
    try:
        if step == "people":
            return JSONResponse(await asyncio.wait_for(try_sim.step_people(tok), timeout=30))
        if step == "launch":
            return JSONResponse(await asyncio.to_thread(try_sim.step_launch, tok))
        if step == "reactions":
            return JSONResponse(await asyncio.wait_for(try_sim.step_reactions(tok), timeout=45))
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
    raise HTTPException(404, "unknown step")
