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


# Free tier: 3 concurrent sessions, ~5 session creates / minute.
_SLOT = threading.Semaphore(int(os.environ.get("BROWSERBASE_MAX_CONCURRENT", "3")))
_CREATE_LOCK = threading.Lock()
_LAST_CREATE_MONO = 0.0
_MIN_CREATE_INTERVAL_S = float(os.environ.get("BROWSERBASE_CREATE_INTERVAL_S", "13"))


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
    cap = int(os.environ.get("BROWSERBASE_MAX_CONCURRENT", "3"))
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
    """Create a Browserbase session respecting concurrent + burst limits."""
    _SLOT.acquire()
    client = Browserbase(api_key=browserbase_api_key())
    kwargs: dict[str, Any] = {"keep_alive": keep_alive}
    pid = browserbase_project_id()
    if pid:
        kwargs["project_id"] = pid
    if proxies:
        kwargs["proxies"] = True

    # Captcha / stealth: env default, explicit kwargs override.
    try:
        from mvp.captcha import browserbase_captcha_kwargs, captcha_solver_enabled

        if solve_captchas is None and advanced_stealth is None and captcha_solver_enabled():
            kwargs.update(browserbase_captcha_kwargs())
    except Exception:
        pass
    if solve_captchas is not None:
        kwargs["solve_captchas"] = bool(solve_captchas)
    if advanced_stealth is not None:
        kwargs["advanced_stealth"] = bool(advanced_stealth)

    # Prefer Browserbase's nested ``browser_settings`` when the SDK accepts it;
    # fall back to flat kwargs for older clients.
    browser_settings: dict[str, Any] = {}
    if "solve_captchas" in kwargs:
        browser_settings["solveCaptchas"] = kwargs.pop("solve_captchas")
    if "advanced_stealth" in kwargs:
        browser_settings["advancedStealth"] = kwargs.pop("advanced_stealth")
    if browser_settings:
        kwargs["browser_settings"] = browser_settings

    try:
        for attempt in range(8):
            try:
                global _LAST_CREATE_MONO
                with _CREATE_LOCK:
                    wait = _MIN_CREATE_INTERVAL_S - (time.monotonic() - _LAST_CREATE_MONO)
                    if wait > 0:
                        time.sleep(wait)
                    try:
                        session = client.sessions.create(**kwargs)
                    except TypeError:
                        # Older SDK: strip unknown nested settings and retry flat.
                        flat = {
                            k: v
                            for k, v in kwargs.items()
                            if k != "browser_settings"
                        }
                        if browser_settings.get("solveCaptchas"):
                            flat["solve_captchas"] = True
                        if browser_settings.get("advancedStealth"):
                            flat["advanced_stealth"] = True
                        try:
                            session = client.sessions.create(**flat)
                        except TypeError:
                            # Last resort: create without captcha flags.
                            basic = {
                                k: v
                                for k, v in flat.items()
                                if k
                                in {"keep_alive", "project_id", "proxies"}
                            }
                            session = client.sessions.create(**basic)
                    _LAST_CREATE_MONO = time.monotonic()
                sid = session.id
                return BrowserbaseSession(
                    id=sid,
                    connect_url=session.connect_url,
                    session_url=f"https://www.browserbase.com/sessions/{sid}",
                )
            except Exception as exc:  # noqa: BLE001
                if _is_rate_limit(exc) and attempt < 7:
                    time.sleep(min(65, 8 * (attempt + 1)))
                    continue
                raise BrowserbaseRateLimitError(str(exc)[:400]) from exc
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
