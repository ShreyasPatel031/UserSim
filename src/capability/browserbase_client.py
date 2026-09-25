"""Browserbase session helpers for capability evals."""

from __future__ import annotations

import os
import random
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
_SLOT_LOCK = threading.Lock()
_HELD_IDS: set[str] = set()
_CREATE_LOCK = threading.Lock()
_LAST_CREATE_MONO = 0.0


def reset_local_slots() -> None:
    """Rebuild the process semaphore after remote sessions were released.

    create_session holds a slot until close_session. Abandoned studies leak
    those slots and the next study deadlocks on acquire.
    """
    global _SLOT
    try:
        cap = int(os.environ.get("BROWSERBASE_MAX_CONCURRENT", "25") or "25")
    except ValueError:
        cap = 25
    with _SLOT_LOCK:
        _SLOT = threading.Semaphore(max(1, cap))
        _HELD_IDS.clear()


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


# Shared Browserbase project with the Sign Up agent. Tag every session we
# create so leftover cleanup can release only ours (never signup / untagged).
BB_OWNER_E2E = "e2e"
BB_OWNER_SIGNUP = "signup"
BB_OWNER_COMPETITOR = "competitor"


def study_session_owner() -> str:
    """Owner tag for study Browserbase sessions.

    Defaults to ``e2e``. Set ``MVP_BB_OWNER=competitor`` for a competitor-pipeline
    run so those sessions can be released without touching signup or other e2e
    work. The signup tag is never used here.
    """
    raw = (os.environ.get("MVP_BB_OWNER") or "").strip().lower()
    # signup sessions are a different pipeline and must never be tagged here.
    if raw in {BB_OWNER_COMPETITOR, "report", BB_OWNER_E2E}:
        return raw
    return BB_OWNER_E2E


@dataclass(frozen=True)
class BrowserbaseSession:
    id: str
    connect_url: str
    session_url: str
    flags: dict[str, Any] | None = None


def session_user_metadata(
    *,
    owner: str = BB_OWNER_E2E,
    study_id: str | None = None,
    **extra: Any,
) -> dict[str, object]:
    """Build Browserbase userMetadata for ownership / study scoping."""
    meta: dict[str, object] = {"owner": str(owner), **extra}
    if study_id:
        meta["study_id"] = str(study_id)
    return meta


def _is_rate_limit(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "too many requests" in msg or "rate limit" in msg


def _is_retryable_create(exc: BaseException) -> bool:
    """429s, hung creates, and transient gateway errors are worth another try.

    Feature refusals (402/403) are not — the caller walks down flag sets.
    """
    if isinstance(exc, TimeoutError):
        return True
    msg = str(exc).lower()
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
        return False
    return _is_rate_limit(exc) or any(
        s in msg
        for s in (
            "503",
            "502",
            "504",
            "timeout",
            "timed out",
            "temporarily",
            "connection reset",
            "connection aborted",
            "concurrency",
        )
    )


def _create_backoff_s(attempt: int, exc: BaseException | None = None) -> float:
    """Jittered backoff so a burst of creates does not hammer Browserbase.

    Hung creates retry quickly (the call already burned its timeout). 429s
    use exponential backoff capped by BROWSERBASE_429_BACKOFF_CAP_S (default
    8s). A flat 45s sleep used to outlive the pre-clock warm window, so tasks
    were created with no real frame and the strict 5s screenshot clock failed.
    These retries still finish before that clock starts.
    """
    is_timeout = isinstance(exc, TimeoutError) or (
        exc is not None and "timed out" in str(exc).lower() and not _is_rate_limit(exc)
    )
    if is_timeout:
        return random.uniform(0.35, 1.25) * (1.0 + 0.3 * max(0, attempt))
    try:
        base = float(os.environ.get("BROWSERBASE_429_BACKOFF_S", "1.5") or "1.5")
    except ValueError:
        base = 1.5
    try:
        cap = float(os.environ.get("BROWSERBASE_429_BACKOFF_CAP_S", "8") or "8")
    except ValueError:
        cap = 8.0
    base = max(0.4, base)
    cap = max(base, cap) if cap > 0 else base
    # Values above the cap (the old hard-coded 45s) stay inside the cap so
    # one create_session returns while warm can still finish pre-clock.
    delay = min(cap, base * (2 ** max(0, attempt)))
    return delay + random.uniform(0.0, max(0.15, delay * 0.35))


def _create_concurrency() -> int:
    try:
        n = int(os.environ.get("BROWSERBASE_CREATE_CONCURRENCY", "2") or "2")
    except ValueError:
        n = 2
    return max(1, min(6, n))


def _create_attempt_timeout_s() -> float:
    try:
        timeout_s = float(os.environ.get("BROWSERBASE_CREATE_TIMEOUT_S", "18") or "18")
    except ValueError:
        timeout_s = 18.0
    return max(0.2, timeout_s)


def _create_attempts() -> int:
    try:
        n = int(os.environ.get("BROWSERBASE_CREATE_ATTEMPTS", "4") or "4")
    except ValueError:
        n = 4
    return max(1, min(6, n))


# In-flight session-create cap. Session slots stay at project concurrency (25);
# bursting 25 creates at once is what trips 429s. Not raised by full-parallel.
_CREATE_SEM = threading.Semaphore(_create_concurrency())


def _release_abandoned_session(session: Any) -> None:
    """Close a session that landed after the caller already timed out."""
    sid = getattr(session, "id", None)
    if not sid:
        return
    try:
        client = Browserbase(api_key=browserbase_api_key())
        client.sessions.update(str(sid), status="REQUEST_RELEASE")
        print(f"Browserbase released abandoned create {sid}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"Browserbase abandoned-session release failed: {exc!r}", flush=True)


def session_flag_attempts(
    *,
    proxies: bool,
    solve_captchas: bool,
    advanced_stealth: bool,
) -> list[dict[str, Any]]:
    """Richest session first, then the signup ladder, then a bare session.

    Signup tries proxies+solve, then solve without proxies, then bare.
    ``advanced_stealth`` stays off on Hobby (403). A proxies-only attempt sits
    ahead of bare so a plan that allows proxies but not captcha-solve still
    gets the proxy.
    """
    attempts: list[dict[str, Any]] = []
    if proxies or solve_captchas or advanced_stealth:
        attempts.append(
            {
                "proxies": bool(proxies),
                "solve_captchas": bool(solve_captchas),
                "advanced_stealth": bool(advanced_stealth),
            }
        )
    if proxies or solve_captchas:
        attempts.append(
            {
                "proxies": bool(proxies),
                "solve_captchas": bool(solve_captchas),
                "advanced_stealth": False,
            }
        )
    # Signup's middle rung: captcha solve on a non-proxy session after a 402.
    if proxies and solve_captchas:
        attempts.append(
            {"proxies": False, "solve_captchas": True, "advanced_stealth": False}
        )
    if proxies:
        attempts.append(
            {"proxies": True, "solve_captchas": False, "advanced_stealth": False}
        )
    attempts.append(
        {"proxies": False, "solve_captchas": False, "advanced_stealth": False}
    )
    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for attempt in attempts:
        key = (attempt["proxies"], attempt["solve_captchas"], attempt["advanced_stealth"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(attempt)
    return unique


def create_session(
    *,
    proxies: bool = False,
    keep_alive: bool = False,
    solve_captchas: bool | None = None,
    advanced_stealth: bool | None = None,
    user_metadata: dict[str, Any] | None = None,
    owner: str | None = None,
    study_id: str | None = None,
) -> BrowserbaseSession:
    """Create a Browserbase session at full Developer concurrency.

    Walks down feature flags on 402/403 so Hobby plans still get a session:
    proxies / advanced stealth / captcha-solve are optional. Session create
    pacing is off unless BROWSERBASE_THROTTLE=1.

    Pass ``user_metadata`` (or ``owner`` / ``study_id``) so shared-project
    cleanup can release only our sessions. Callers that omit metadata stay
    untagged — kill_all will leave those alone.
    """
    ensure_browserbase_full_parallel()
    try:
        slot_wait = float(os.environ.get("BROWSERBASE_SLOT_WAIT_S", "20") or "20")
    except ValueError:
        slot_wait = 20.0
    held = _SLOT.acquire(timeout=max(1.0, slot_wait))
    if not held:
        print(
            "Browserbase local slot acquire timed out — creating anyway (stale slots)",
            flush=True,
        )
    client = Browserbase(api_key=browserbase_api_key())
    pid = browserbase_project_id()

    meta: dict[str, object] | None = None
    if user_metadata:
        meta = {str(k): v for k, v in user_metadata.items()}
    if owner is not None or study_id is not None:
        base = session_user_metadata(
            owner=owner or BB_OWNER_E2E,
            study_id=study_id,
        )
        if meta:
            base.update(meta)
            meta = base
        else:
            meta = base

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

    unique_attempts = session_flag_attempts(
        proxies=bool(proxies),
        solve_captchas=bool(want_solve),
        advanced_stealth=bool(want_stealth),
    )

    def _build_kwargs(flags: dict[str, Any]) -> dict[str, Any]:
        # Project defaultTimeout is often 300s — parallel agents + LLM steps
        # overrun that and Browserbase kills the CDP socket (HTTP 410).
        try:
            session_timeout_s = int(os.environ.get("BROWSERBASE_SESSION_TIMEOUT_S", "1800"))
        except ValueError:
            session_timeout_s = 1800
        session_timeout_s = max(60, min(21600, session_timeout_s))
        kwargs: dict[str, Any] = {
            "keep_alive": keep_alive,
            # SDK Python name; serialized as "timeout" for the API.
            "api_timeout": session_timeout_s,
        }
        if pid:
            kwargs["project_id"] = pid
        if flags.get("proxies"):
            kwargs["proxies"] = True
        if meta:
            kwargs["user_metadata"] = meta
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
            # Older SDKs may want timeout= instead of api_timeout=.
            if "api_timeout" in flat and "timeout" not in flat:
                flat["timeout"] = flat.pop("api_timeout")
            bs = kwargs.get("browser_settings") or {}
            if bs.get("solveCaptchas"):
                flat["solve_captchas"] = True
            if bs.get("advancedStealth"):
                flat["advanced_stealth"] = True
            try:
                return client.sessions.create(**flat)
            except TypeError:
                # Drop metadata last — older SDKs may not accept it.
                basic = {
                    k: v
                    for k, v in flat.items()
                    if k
                    in {
                        "keep_alive",
                        "project_id",
                        "proxies",
                        "api_timeout",
                        "timeout",
                        "user_metadata",
                    }
                }
                try:
                    return client.sessions.create(**basic)
                except TypeError:
                    bare = {
                        k: v
                        for k, v in basic.items()
                        if k in {"keep_alive", "project_id", "proxies", "api_timeout", "timeout"}
                    }
                    return client.sessions.create(**bare)

    def _create_once_bounded(kwargs: dict[str, Any], *, timeout_s: float) -> Any:
        """Don't let the Browserbase SDK retry loop block a study forever.

        If the HTTP call lands a session after we have already given up, release
        that session. An orphaned create is what fills the project and turns the
        next warm into a 429.
        """
        box: dict[str, Any] = {}
        abandoned = threading.Event()

        def _run() -> None:
            try:
                session = _create_once(kwargs)
            except Exception as exc:  # noqa: BLE001
                box["exc"] = exc
                return
            if abandoned.is_set():
                _release_abandoned_session(session)
                box["abandoned"] = True
                return
            box["session"] = session

        worker = threading.Thread(target=_run, daemon=True, name="bb-create")
        worker.start()
        worker.join(timeout_s)
        if worker.is_alive():
            abandoned.set()
            raise TimeoutError(
                f"Browserbase session create timed out after {timeout_s:.0f}s"
            )
        if box.get("abandoned"):
            raise TimeoutError("Browserbase session create abandoned after timeout")
        if "exc" in box:
            raise box["exc"]
        return box["session"]

    attempts_n = _create_attempts()
    timeout_s = _create_attempt_timeout_s()
    last_exc: BaseException | None = None
    try:
        for flags in unique_attempts:
            kwargs = _build_kwargs(flags)
            for attempt in range(attempts_n):
                sem_held = _CREATE_SEM.acquire(timeout=max(1.0, min(8.0, timeout_s)))
                plan_refusal = False
                retry_delay: float | None = None
                if not sem_held:
                    last_exc = TimeoutError(
                        "Browserbase create concurrency cap busy"
                    )
                    if attempt < attempts_n - 1:
                        delay = _create_backoff_s(attempt, last_exc)
                        print(
                            f"Browserbase create cap busy — backing off {delay:.1f}s "
                            f"(attempt {attempt + 1}/{attempts_n})",
                            flush=True,
                        )
                        time.sleep(delay)
                        continue
                    break
                try:
                    global _LAST_CREATE_MONO
                    # Stagger starts so parallel warms are not one burst.
                    jitter = random.uniform(0.05, 0.55)
                    with _CREATE_LOCK:
                        interval = _create_interval_s()
                        wait = max(
                            0.0, interval - (time.monotonic() - _LAST_CREATE_MONO)
                        )
                        wait = max(wait, jitter if attempt == 0 else 0.0)
                        if wait > 0:
                            time.sleep(wait)
                        _LAST_CREATE_MONO = time.monotonic()
                    session = _create_once_bounded(kwargs, timeout_s=timeout_s)
                    sid = session.id
                    if held:
                        with _SLOT_LOCK:
                            _HELD_IDS.add(sid)
                    print(
                        f"Browserbase session {sid} flags={flags}",
                        flush=True,
                    )
                    return BrowserbaseSession(
                        id=sid,
                        connect_url=session.connect_url,
                        session_url=f"https://www.browserbase.com/sessions/{sid}",
                        flags=dict(flags),
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
                        plan_refusal = True
                    elif _is_retryable_create(exc) and attempt < attempts_n - 1:
                        retry_delay = _create_backoff_s(attempt, exc)
                        kind = (
                            "timeout" if isinstance(exc, TimeoutError) else "rate-limit"
                        )
                        print(
                            f"Browserbase create {kind} — backing off {retry_delay:.1f}s "
                            f"(attempt {attempt + 1}/{attempts_n})",
                            flush=True,
                        )
                    else:
                        raise BrowserbaseRateLimitError(str(exc)[:400]) from exc
                finally:
                    # Release the create slot before sleeping so other warms proceed.
                    if sem_held:
                        _CREATE_SEM.release()
                if plan_refusal:
                    break
                if retry_delay is not None:
                    time.sleep(retry_delay)
                    continue
        raise BrowserbaseRateLimitError(
            str(last_exc)[:400] if last_exc else "session create failed"
        )
    except Exception:
        if held:
            _SLOT.release()
        raise


def close_session(session_id: str) -> None:
    client = Browserbase(api_key=browserbase_api_key())
    try:
        client.sessions.update(session_id, status="REQUEST_RELEASE")
    except Exception:
        pass
    finally:
        with _SLOT_LOCK:
            if session_id in _HELD_IDS:
                _HELD_IDS.discard(session_id)
                _SLOT.release()


def session_live_view_url(session_id: str) -> str | None:
    """Embeddable live view of a running Browserbase session (fullscreen debugger)."""
    if not session_id:
        return None
    try:
        client = Browserbase(api_key=browserbase_api_key())
        urls = client.sessions.debug(session_id)
        return (
            getattr(urls, "debugger_fullscreen_url", None)
            or getattr(urls, "debuggerFullscreenUrl", None)
            or (urls.get("debuggerFullscreenUrl") if isinstance(urls, dict) else None)
        )
    except Exception:
        return None
