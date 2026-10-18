"""Caps for the public MCP endpoint, read from limits.json on main.

limits.json (next to this file) is the single place the caps live. The server loads the bundled copy at startup
and re-reads the copy on main (MVP_MCP_LIMITS_URL, default the raw GitHub URL) every ``refresh_s`` seconds, so
merging a PR that edits the file changes the running server without a redeploy. An env var named
MVP_MCP_<KEY upper case> overrides one value on one server (optional). A bad remote file is ignored and the last
good values stay in force.

Spend for callers without a token is an estimate (est_usd_per_session + est_usd_per_step per step), kept per
client IP and in total per America/Los_Angeles day, and saved to MVP_MCP_SPEND_FILE so a restart doesn't reset it.
"""

from __future__ import annotations

import datetime as _dt
import ipaddress
import json
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

BUNDLED = Path(__file__).with_name("limits.json")
DEFAULT_URL = "https://raw.githubusercontent.com/ShreyasPatel031/UserSim/main/mvp/sim_mcp/limits.json"

# Used only if limits.json is missing a key (or unreadable). Keep in step with limits.json.
DEFAULTS: dict[str, Any] = {
    "refresh_s": 300,
    "allow_anonymous": True,
    "max_sessions": 10,
    "max_per_client": 8,
    "anon_max_concurrent_sessions_per_ip": 3,
    "anon_daily_usd_per_ip": 2.0,
    "anon_daily_usd_global": 10.0,
    "est_usd_per_session": 0.1,
    "est_usd_per_step": 0.01,
    "anon_max_cells_per_study": 12,
    "anon_allow_sms": False,
    "anon_allow_paid_captcha": False,
    "anon_allow_shared_aliases": False,
}

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"values": {}, "source": "", "loaded_at": 0.0, "checked_at": 0.0, "error": "", "fetching": False}


def parse(text: str) -> dict[str, Any]:
    """{key: value} from limits.json text. Unknown keys and values of the wrong type are dropped."""
    data = json.loads(text)
    rows = data.get("limits") if isinstance(data, dict) else None
    if not isinstance(rows, dict):
        raise ValueError("limits.json needs a top-level 'limits' object")
    out: dict[str, Any] = {}
    for key, row in rows.items():
        if key not in DEFAULTS:
            continue
        val = row.get("value") if isinstance(row, dict) else row
        want = DEFAULTS[key]
        if isinstance(want, bool):
            if isinstance(val, bool):
                out[key] = val
        elif isinstance(val, (int, float)) and not isinstance(val, bool) and val >= 0:
            out[key] = type(want)(val) if isinstance(want, int) and float(val).is_integer() else float(val)
    return out


def _set(values: dict[str, Any], source: str) -> None:
    with _LOCK:
        _STATE.update(values=values, source=source, loaded_at=time.time(), error="")


def load_bundled() -> None:
    try:
        _set(parse(BUNDLED.read_text()), f"bundled:{BUNDLED.name}")
    except Exception as exc:  # noqa: BLE001
        with _LOCK:
            _STATE["error"] = f"bundled limits.json unreadable: {exc!r}"[:300]


def _url() -> str:
    return (os.environ.get("MVP_MCP_LIMITS_URL") or DEFAULT_URL).strip()


def refresh_now() -> bool:
    """Fetch limits.json from main. True if it was applied."""
    url = _url()
    if url.lower() in {"", "0", "off", "none"}:
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "usersim-mcp-limits", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (fixed https URL from config)
            values = parse(resp.read(200_000).decode("utf-8"))
        _set(values, url)
        return True
    except Exception as exc:  # noqa: BLE001
        with _LOCK:
            _STATE["error"] = f"refresh from {url} failed, keeping {_STATE['source'] or 'defaults'}: {exc!r}"[:300]
        print(f"[mcp limits] {_STATE['error']}", flush=True)
        return False
    finally:
        with _LOCK:
            _STATE["checked_at"] = time.time()
            _STATE["fetching"] = False


def _maybe_refresh() -> None:
    every = max(30.0, float(_raw("refresh_s")))
    with _LOCK:
        if _STATE["fetching"] or time.time() - _STATE["checked_at"] < every:
            return
        _STATE["fetching"] = True
        _STATE["checked_at"] = time.time()
    threading.Thread(target=refresh_now, name="mcp-limits-refresh", daemon=True).start()


def _raw(key: str) -> Any:
    if not _STATE["values"] and not _STATE["source"]:
        load_bundled()
    return _STATE["values"].get(key, DEFAULTS[key])


def get(key: str) -> Any:
    """Current value: env override MVP_MCP_<KEY>, else limits.json (refreshed from main), else DEFAULTS."""
    _maybe_refresh()
    env = os.environ.get("MVP_MCP_" + key.upper())
    want = DEFAULTS[key]
    if env is not None and env.strip() != "":
        try:
            if isinstance(want, bool):
                return env.strip().lower() in {"1", "true", "yes", "on"}
            return type(want)(float(env)) if isinstance(want, int) else float(env)
        except ValueError:
            pass
    return _raw(key)


def snapshot() -> dict[str, Any]:
    """Effective values plus where they came from (for /api/mcp/limits)."""
    vals = {k: get(k) for k in DEFAULTS}
    overrides = sorted(k for k in DEFAULTS if (os.environ.get("MVP_MCP_" + k.upper()) or "").strip())
    with _LOCK:
        st = dict(_STATE)
    return {"values": vals, "source": st["source"], "loaded_at": st["loaded_at"], "checked_at": st["checked_at"],
            "error": st["error"], "env_overrides": overrides, "today": today(), "spend": spend_summary()}


# ---------------------------------------------------------------- client IP

def client_ip(headers: dict[str, str], peer: str) -> str:
    """The caller's IP. X-Forwarded-For is trusted only from a proxy on the same machine (caddy / cloudflared on the
    VM talk to uvicorn over 127.0.0.1), and then only its LAST entry, the one that proxy wrote: a client can put anything in
    the earlier entries, so the first entry would let it pick its own cap bucket."""
    peer = (peer or "").strip()
    try:
        local = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        local = False
    if local:
        fwd = [p.strip() for p in (headers.get("x-forwarded-for") or "").split(",") if p.strip()]
        if fwd:
            return fwd[-1]
    return peer


# ---------------------------------------------------------------- spend ledger (callers without a token)

_SPEND: dict[str, Any] = {"day": "", "ip": {}, "total": 0.0}
_SPEND_LOADED = False


def today() -> str:
    try:
        from zoneinfo import ZoneInfo

        return _dt.datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:  # noqa: BLE001
        return _dt.datetime.utcnow().date().isoformat()


def _spend_path() -> str:
    return os.environ.get("MVP_MCP_SPEND_FILE", "/var/lib/usersim/mcp_anon_spend.json")


def _load_spend() -> None:
    global _SPEND_LOADED
    if _SPEND_LOADED:
        return
    _SPEND_LOADED = True
    try:
        data = json.loads(Path(_spend_path()).read_text())
        if isinstance(data, dict) and data.get("day") == today():
            _SPEND.update(day=data["day"], ip=dict(data.get("ip") or {}), total=float(data.get("total") or 0))
    except Exception:  # noqa: BLE001
        pass


def _roll() -> None:
    _load_spend()
    if _SPEND["day"] != today():
        _SPEND.update(day=today(), ip={}, total=0.0)


def _save() -> None:
    path = Path(_spend_path())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(_SPEND))
        tmp.replace(path)
    except Exception:  # noqa: BLE001
        pass  # in memory still works


class CapExceeded(Exception):
    """A cap for callers without a token was hit. str() is the message for the client."""

    def __init__(self, limit: str, message: str) -> None:
        super().__init__(message)
        self.limit = limit


def spent(ip: str) -> tuple[float, float]:
    with _LOCK:
        _roll()
        return float(_SPEND["ip"].get(ip, 0.0)), float(_SPEND["total"])


def charge(ip: str, usd: float, what: str, *, dry: bool = False) -> None:
    """Add usd for ip (the caller's key), or raise CapExceeded if that would pass the per-IP or the global daily
    cap. dry=True only checks."""
    per_ip, glob = float(get("anon_daily_usd_per_ip")), float(get("anon_daily_usd_global"))
    with _LOCK:
        _roll()
        mine, total = float(_SPEND["ip"].get(ip, 0.0)), float(_SPEND["total"])
        if total + usd > glob + 1e-9:
            raise CapExceeded("anon_daily_usd_global", (
                f"UserSim's daily budget for callers without a token is used up (${total:.2f} of ${glob:.2f}, "
                f"{what} needs ${usd:.2f}). It resets at midnight America/Los_Angeles. Callers with a token are not "
                "affected. Limits: mvp/sim_mcp/limits.json on main."))
        if mine + usd > per_ip + 1e-9:
            raise CapExceeded("anon_daily_usd_per_ip", (
                f"this client IP has used its daily UserSim budget (${mine:.2f} of ${per_ip:.2f}, {what} needs "
                f"${usd:.2f}). It resets at midnight America/Los_Angeles. Finish open sessions with usersim_finish "
                "(always allowed). Limits: mvp/sim_mcp/limits.json on main."))
        if dry:
            return
        _SPEND["ip"][ip] = round(mine + usd, 6)
        _SPEND["total"] = round(total + usd, 6)
        _save()


def spend_summary() -> dict[str, Any]:
    with _LOCK:
        _roll()
        return {"day": _SPEND["day"], "total_usd": round(float(_SPEND["total"]), 4), "ips": len(_SPEND["ip"])}


def reset_for_tests() -> None:
    global _SPEND_LOADED
    with _LOCK:
        _SPEND.update(day="", ip={}, total=0.0)
        _SPEND_LOADED = True
        _STATE.update(values={}, source="", loaded_at=0.0, checked_at=time.time(), error="", fetching=False)
