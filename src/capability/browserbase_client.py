"""Browserbase session helpers for capability evals."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from browserbase import Browserbase

from config import ROOT


class BrowserbaseConfigError(RuntimeError):
    pass


class BrowserbaseRateLimitError(RuntimeError):
    pass


def ensure_browserbase_full_parallel() -> None:
    """Force Developer-plan parallelism (project concurrency is 25).

    Cursor/cloud secrets often still inject free-tier pacing
    (BROWSERBASE_CREATE_INTERVAL_S=8, low MVP_BROWSER_CONCURRENCY). Those
    serialize session creates and make studies look stuck. Opt into throttling
    only with BROWSERBASE_THROTTLE=1.
    """
    if os.environ.get("BROWSERBASE_THROTTLE", "").lower() in {"1", "true", "yes"}:
        return
    os.environ["BROWSERBASE_CREATE_INTERVAL_S"] = "0"
    try:
        max_c = int(os.environ.get("BROWSERBASE_MAX_CONCURRENT") or "25")
    except ValueError:
        max_c = 25
    os.environ["BROWSERBASE_MAX_CONCURRENT"] = str(max(25, max_c))
    try:
        browser_c = int(os.environ.get("MVP_BROWSER_CONCURRENCY") or "25")
    except ValueError:
        browser_c = 25
    os.environ["MVP_BROWSER_CONCURRENCY"] = str(max(25, browser_c))


ensure_browserbase_full_parallel()

# Developer project default is 25 concurrent (see Browserbase project.concurrency).
# Create pacing is off unless BROWSERBASE_THROTTLE=1.
_SLOT = threading.Semaphore(int(os.environ.get("BROWSERBASE_MAX_CONCURRENT", "25")))
_CREATE_LOCK = threading.Lock()
_LAST_CREATE_MONO = 0.0


def _create_interval_s() -> float:
    if os.environ.get("BROWSERBASE_THROTTLE", "").lower() in {"1", "true", "yes"}:
        return float(os.environ.get("BROWSERBASE_CREATE_INTERVAL_S", "8") or "8")
    return 0.0


def _read_secret(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if val:
        return val
    env_file = ROOT / "secrets" / "env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def browserbase_api_key() -> str:
    key = _read_secret("BROWSERBASE_API_KEY")
    if not key:
        raise BrowserbaseConfigError("BROWSERBASE_API_KEY is not set (see secrets/env)")
    return key


def browserbase_project_id() -> str | None:
    pid = _read_secret("BROWSERBASE_PROJECT_ID")
    return pid or None


def browserbase_enabled() -> bool:
    return os.environ.get("USE_BROWSERBASE", "").lower() in {"1", "true", "yes"}


def browserbase_max_workers(requested: int) -> int:
    if not browserbase_enabled():
        return max(1, requested)
    ensure_browserbase_full_parallel()
    cap = int(os.environ.get("BROWSERBASE_MAX_CONCURRENT", "25"))
    return max(1, min(requested, cap))


@dataclass(frozen=True)
class BrowserbaseSession:
    id: str
    connect_url: str
    session_url: str


def _is_rate_limit(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "too many requests" in msg or "rate limit" in msg


def create_session(
    *,
    proxies: bool = False,
    keep_alive: bool = False,
    solve_captchas: bool | None = None,
    advanced_stealth: bool | None = None,
) -> BrowserbaseSession:
    """Create a Browserbase session at full Developer concurrency.

    Walks down feature flags on 402/403 so Hobby plans still get a session:
    proxies / advanced stealth / captcha-solve are optional. Session create
    pacing is off unless BROWSERBASE_THROTTLE=1.
    """
    ensure_browserbase_full_parallel()
    _SLOT.acquire()
    client = Browserbase(api_key=browserbase_api_key())
    pid = browserbase_project_id()

    # Captcha / stealth: env default, explicit kwargs override.
    default_solve: bool | None = None
    default_stealth: bool | None = None
    try:
        from mvp.captcha import browserbase_captcha_kwargs, captcha_solver_enabled

        if solve_captchas is None and advanced_stealth is None and captcha_solver_enabled():
            caps = browserbase_captcha_kwargs()
            default_solve = bool(caps.get("solve_captchas"))
            default_stealth = bool(caps.get("advanced_stealth"))
    except Exception:
        pass

    want_solve = default_solve if solve_captchas is None else bool(solve_captchas)
    want_stealth = default_stealth if advanced_stealth is None else bool(advanced_stealth)

    # Ordered attempts: richest → bare session. Enterprise flags first so paid
    # plans keep them; Hobby gets a working basic session after 402/403.
    attempts: list[dict[str, Any]] = []
    if proxies or want_solve or want_stealth:
        attempts.append(
            {"proxies": bool(proxies), "solve_captchas": bool(want_solve), "advanced_stealth": bool(want_stealth)}
        )
    if proxies or want_solve:
        attempts.append(
            {"proxies": bool(proxies), "solve_captchas": bool(want_solve), "advanced_stealth": False}
        )
    if proxies:
        attempts.append({"proxies": True, "solve_captchas": False, "advanced_stealth": False})
    attempts.append({"proxies": False, "solve_captchas": False, "advanced_stealth": False})
    # De-dupe while preserving order.
    seen: set[tuple[Any, ...]] = set()
    unique_attempts: list[dict[str, Any]] = []
    for a in attempts:
        key = (a["proxies"], a["solve_captchas"], a["advanced_stealth"])
        if key in seen:
            continue
        seen.add(key)
        unique_attempts.append(a)

    def _build_kwargs(flags: dict[str, Any]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"keep_alive": keep_alive}
        if pid:
            kwargs["project_id"] = pid
        if flags.get("proxies"):
            kwargs["proxies"] = True
        browser_settings: dict[str, Any] = {}
        if flags.get("solve_captchas"):
            browser_settings["solveCaptchas"] = True
        if flags.get("advanced_stealth"):
            browser_settings["advancedStealth"] = True
        if browser_settings:
            kwargs["browser_settings"] = browser_settings
        return kwargs

    def _create_once(kwargs: dict[str, Any]) -> Any:
        try:
            return client.sessions.create(**kwargs)
        except TypeError:
            flat = {k: v for k, v in kwargs.items() if k != "browser_settings"}
            bs = kwargs.get("browser_settings") or {}
            if bs.get("solveCaptchas"):
                flat["solve_captchas"] = True
            if bs.get("advancedStealth"):
                flat["advanced_stealth"] = True
            try:
                return client.sessions.create(**flat)
            except TypeError:
                basic = {
                    k: v
                    for k, v in flat.items()
                    if k in {"keep_alive", "project_id", "proxies"}
                }
                return client.sessions.create(**basic)

    last_exc: BaseException | None = None
    try:
        for flags in unique_attempts:
            kwargs = _build_kwargs(flags)
            for attempt in range(8):
                try:
                    global _LAST_CREATE_MONO
                    with _CREATE_LOCK:
                        interval = _create_interval_s()
                        if interval > 0:
                            wait = interval - (time.monotonic() - _LAST_CREATE_MONO)
                            if wait > 0:
                                time.sleep(wait)
                        session = _create_once(kwargs)
                        _LAST_CREATE_MONO = time.monotonic()
                    sid = session.id
                    return BrowserbaseSession(
                        id=sid,
                        connect_url=session.connect_url,
                        session_url=f"https://www.browserbase.com/sessions/{sid}",
                    )
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    msg = str(exc).lower()
                    # Plan / feature refusal → try next (weaker) flag set.
                    if any(
                        s in msg
                        for s in (
                            "403",
                            "402",
                            "forbidden",
                            "payment required",
                            "verified mode",
                            "enterprise",
                            "not available",
                            "upgrade",
                        )
                    ):
                        break
                    if _is_rate_limit(exc) and attempt < 7:
                        time.sleep(min(65, 8 * (attempt + 1)))
                        continue
                    raise BrowserbaseRateLimitError(str(exc)[:400]) from exc
        raise BrowserbaseRateLimitError(str(last_exc)[:400] if last_exc else "session create failed")
    except Exception:
        _SLOT.release()
        raise


def close_session(session_id: str) -> None:
    client = Browserbase(api_key=browserbase_api_key())
    try:
        client.sessions.update(session_id, status="REQUEST_RELEASE")
    except Exception:
        pass
    finally:
        _SLOT.release()
