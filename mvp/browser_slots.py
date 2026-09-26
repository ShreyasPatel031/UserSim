"""One Browserbase study at a time, queued instead of failing.

The Browserbase project has a fixed number of concurrent sessions (25). A
24-agent study needs nearly all of them, and other servers (the VM, a local
box, a signup run) share the same project. A study that starts while the
slots are taken used to fail session creates or stall agents half-open.

Before a study opens browsers it takes a ticket here. It starts when this
server has no other study running AND Browserbase has enough free sessions
for its agents. Until then the study shows status "queued" with an estimate
of when it will start. When the study ends, crashes, or is cancelled, the
sessions tagged with its id are released.
"""
from __future__ import annotations

import asyncio
import collections
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

_TICKETS: collections.deque[str] = collections.deque()
_ACTIVE: dict[str, float] = {}  # study id -> monotonic start
_COUNT_CACHE: dict[str, Any] = {"at": 0.0, "value": None}
_COUNT_TASK: asyncio.Task | None = None
_OBJS: dict[str, Any] = {}  # study id -> study, for progress-based estimates
_RECENT_S: collections.deque[float] = collections.deque(maxlen=5)  # recent study durations here


def session_cap() -> int:
    try:
        return max(1, int(os.environ.get("BROWSERBASE_MAX_CONCURRENT") or "25"))
    except ValueError:
        return 25


def typical_study_s() -> float:
    """Median of the last few studies on this server, else MVP_TYPICAL_STUDY_S (180s)."""
    if _RECENT_S:
        ordered = sorted(_RECENT_S)
        return ordered[len(ordered) // 2]
    try:
        return float(os.environ.get("MVP_TYPICAL_STUDY_S") or "180")
    except ValueError:
        return 180.0


def _progress_remaining_s(study: Any, elapsed: float) -> float | None:
    """From the running study's own agents: elapsed x (left / done), once a fair share finished."""
    live = getattr(study, "live_sessions", None) or {}
    rows = [r for r in live.values() if isinstance(r, dict)] if isinstance(live, dict) else []
    if len(rows) < 4:
        return None
    done = sum(1 for r in rows if str(r.get("status") or "") in {"complete", "done", "error", "killed", "failed"})
    frac = done / len(rows)
    if frac < 0.3:
        return None
    # The last agents (sign-ups, long paths) run longer than the median one.
    return elapsed * (1 - frac) / frac * 1.5 + 10


def max_wait_s() -> float:
    try:
        return float(os.environ.get("MVP_QUEUE_MAX_WAIT_S") or "600")
    except ValueError:
        return 600.0


def needed_sessions(study: Any) -> int:
    """Sessions this study opens at once: its agent cap (default 24), within the project cap."""
    want = int(getattr(study, "max_agents", 0) or 0) or int(os.environ.get("MVP_DEFAULT_AGENTS") or "24")
    return max(1, min(want, session_cap()))


def _enabled() -> bool:
    if os.environ.get("MVP_BROWSER_QUEUE", "1").lower() in {"0", "false", "no"}:
        return False
    if os.environ.get("USE_BROWSERBASE", "").lower() not in {"1", "true", "yes"}:
        return False
    try:
        from capability.browserbase_client import browserbase_api_key

        return bool(browserbase_api_key())
    except Exception:
        return False


def _age_s(raw: Any) -> float | None:
    if not raw:
        return None
    try:
        if isinstance(raw, datetime):
            dt = raw
        else:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return None


def running_sessions() -> dict[str, Any] | None:
    """RUNNING sessions on the whole project (every owner) and their ages. None when unknown."""
    from mvp.kill_switch import list_running_browserbase

    rows = list_running_browserbase(owner="*")
    if rows and rows[0].get("status") == "error":
        return None
    ages = [a for a in (_age_s(r.get("started_at") or r.get("created_at")) for r in rows) if a is not None]
    ages.sort()
    window = burst_window_s()
    recent = [a for a in ages if a < window]
    return {
        "n": len(rows),
        "median_age_s": ages[len(ages) // 2] if ages else None,
        # Creates still inside Browserbase's rolling burst window, from every
        # server on the project (still-running ones; released ones are
        # invisible here, the local bucket covers this process).
        "recent_ages_s": recent,
    }


def burst_window_s() -> float:
    try:
        from capability.bb_rate import create_bucket

        return float(create_bucket().window_s)
    except Exception:
        return 60.0


def burst_needed(need: int) -> int:
    """Create tokens a study wants free before it starts.

    The first ``need - slack`` creates (default slack 6) are what the product
    agents and most rivals get at once; the rest may wait in the bucket a few
    seconds without failing.
    """
    try:
        from capability.bb_rate import create_bucket

        cap = create_bucket().capacity
    except Exception:
        cap = 22
    try:
        slack = int(os.environ.get("MVP_QUEUE_BURST_SLACK") or "6")
    except ValueError:
        slack = 6
    return max(1, min(need, cap) - max(0, slack))


def burst_state(need: int, counted: dict[str, Any] | None) -> dict[str, Any]:
    """Creates in the last window (max of this process's bucket and the project list) and when room opens."""
    want = burst_needed(need)
    try:
        from capability.bb_rate import create_bucket

        bucket = create_bucket()
        cap, window = bucket.capacity, bucket.window_s
        local_recent = bucket.recent()
        local_eta = bucket.room_in(want)
    except Exception:
        cap, window, local_recent, local_eta = 22, 60.0, 0, 0.0
    remote = sorted((counted or {}).get("recent_ages_s") or [], reverse=True)  # oldest first
    remote_eta = 0.0
    over = len(remote) + want - cap
    if over > 0:
        remote_eta = max(0.0, window - float(remote[over - 1]))
    recent = max(local_recent, len(remote))
    return {
        "recent": recent,
        "capacity": cap,
        "want": want,
        "ok": local_eta <= 0 and remote_eta <= 0,
        "eta_s": max(local_eta, remote_eta),
    }


async def _fetch_count() -> dict[str, Any] | None:
    try:
        value = await asyncio.wait_for(asyncio.to_thread(running_sessions), timeout=4)
    except Exception:
        value = None
    _COUNT_CACHE["at"] = time.monotonic()
    _COUNT_CACHE["value"] = value
    return value


def prefetch_count() -> None:
    """Start counting Browserbase sessions now (while the plan is written), so the gate adds no time."""
    global _COUNT_TASK
    if not _enabled():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _COUNT_TASK is None or _COUNT_TASK.done():
        _COUNT_TASK = loop.create_task(_fetch_count())


async def _count(max_age_s: float = 5.0) -> dict[str, Any] | None:
    if _COUNT_TASK is not None and not _COUNT_TASK.done():
        try:
            return await asyncio.shield(_COUNT_TASK)
        except Exception:
            return None
    if time.monotonic() - float(_COUNT_CACHE["at"] or 0.0) <= max_age_s:
        return _COUNT_CACHE["value"]
    return await _fetch_count()


def queue_eta_s(position: int, counted: dict[str, Any] | None) -> int:
    """Seconds until a queued study likely starts: the running study's remaining time, plus one study per place ahead."""
    typical = typical_study_s()
    remaining = None
    if _ACTIVE:
        sid, began = min(_ACTIVE.items(), key=lambda kv: kv[1])
        elapsed = time.monotonic() - began
        remaining = typical - elapsed
        by_progress = _progress_remaining_s(_OBJS.get(sid), elapsed) if sid in _OBJS else None
        if by_progress is not None:
            remaining = by_progress
    elif counted and counted.get("median_age_s") is not None:
        remaining = typical - float(counted["median_age_s"])
    if remaining is None:
        remaining = typical / 2
    return int(max(10.0, remaining) + typical * max(0, position))


def queue_snapshot() -> dict[str, Any]:
    snap: dict[str, Any] = {"active": list(_ACTIVE), "queued": list(_TICKETS)}
    try:
        from capability.bb_rate import create_bucket

        bucket = create_bucket()
        snap["creates_last_60s"] = bucket.recent()
        snap["create_burst_cap"] = bucket.capacity
        snap["create_waiters"] = bucket.waiting()
    except Exception:
        pass
    return snap


async def acquire(study: Any, touch: Callable[..., None]) -> None:
    """Wait for this server's turn and enough free Browserbase sessions, showing a queued state."""
    if not _enabled():
        _ACTIVE[study.id] = time.monotonic()
        return
    try:
        from mvp.preopen import take_admission

        preadmitted = take_admission(study.id)
    except Exception:
        preadmitted = False
    if preadmitted:
        # Admitted at submit, when its product browsers were pre-opened; a
        # recount now would count those browsers as another run's.
        study.queue_eta_s = None
        study.queue_position = None
        study.queued_s = 0.0
        _ACTIVE[study.id] = time.monotonic()
        _OBJS[study.id] = study
        _COUNT_CACHE["at"] = 0.0
        return
    need = needed_sessions(study)
    _TICKETS.append(study.id)
    started = time.monotonic()
    shown = False
    try:
        while True:
            ahead = list(_TICKETS).index(study.id)
            counted: dict[str, Any] | None = None
            reason = ""
            burst_eta: int | None = None
            if ahead == 0 and not _ACTIVE:
                counted = await _count(max_age_s=5.0 if not shown else 0.0)
                n = int(counted["n"]) if counted else 0
                free = session_cap() - n
                burst = burst_state(need, counted)
                if (counted is None or free >= need) and burst["ok"]:
                    break
                if counted is not None and free < need:
                    reason = f"{n} of {session_cap()} browsers are busy with another run"
                else:
                    # Browserbase allows 25 new browsers per rolling minute.
                    reason = (
                        f"{burst['recent']} browsers were opened in the last minute "
                        f"(Browserbase allows {burst['capacity']} new ones a minute here)"
                    )
                    burst_eta = int(burst["eta_s"]) + 1
            elif _ACTIVE:
                reason = "another study is using the browsers"
            else:
                reason = f"{ahead} study ahead in the queue" if ahead == 1 else f"{ahead} studies ahead in the queue"
            waited = time.monotonic() - started
            if waited > max_wait_s():
                print(f"study {study.id}: browsers still busy after {int(waited)}s; starting anyway", flush=True)
                break
            if burst_eta is not None:
                eta = max(1, burst_eta)
            else:
                eta = queue_eta_s(ahead + (1 if _ACTIVE and ahead else 0), counted)
            study.queue_eta_s = eta
            study.queue_position = ahead + 1
            touch(f"Queued: {reason}. Starting in ~{eta}s", "queued")
            if not shown:
                shown = True
                try:
                    from mvp.study import log_activity

                    log_activity(study, "phase", f"Queued: {reason}")
                except Exception:
                    pass
            await asyncio.sleep(3 if burst_eta is None else max(1.0, min(3.0, float(burst_eta))))
    finally:
        try:
            _TICKETS.remove(study.id)
        except ValueError:
            pass
    study.queue_eta_s = None
    study.queue_position = None
    study.queued_s = round(time.monotonic() - started, 1) if shown else 0.0
    _ACTIVE[study.id] = time.monotonic()
    _OBJS[study.id] = study
    # Sessions opened from here on count against the next caller's check.
    _COUNT_CACHE["at"] = 0.0


def release_study_sessions(study_id: str) -> int:
    """REQUEST_RELEASE every RUNNING session tagged with this study (agents, warms, signups under it)."""
    if not study_id or not _enabled():
        return 0
    from mvp.kill_switch import list_running_browserbase, release_browserbase_session

    released = 0
    for row in list_running_browserbase(owner="*"):
        if row.get("status") == "error":
            break
        tag = str(row.get("study_id") or "")
        if row.get("owner") == "signup" and not tag.startswith(study_id):
            continue
        if tag == study_id or tag.startswith(study_id + "_"):
            if release_browserbase_session(str(row.get("id") or "")):
                released += 1
    return released


def release(study: Any) -> None:
    """End of a study (finished, failed, or cancelled): free the turn and any leftover sessions."""
    try:
        from mvp.preopen import release as _preopen_release

        asyncio.get_running_loop().create_task(_preopen_release(study.id))
    except Exception:
        pass
    began = _ACTIVE.pop(study.id, None)
    _OBJS.pop(study.id, None)
    if began is not None and str(getattr(study, "status", "")) == "complete":
        _RECENT_S.append(time.monotonic() - began)
    _COUNT_CACHE["at"] = 0.0

    async def _later() -> None:
        # Agents close their own sessions; give them a moment, then sweep leftovers.
        await asyncio.sleep(5)
        try:
            n = await asyncio.wait_for(asyncio.to_thread(release_study_sessions, study.id), timeout=30)
            if n:
                print(f"study {study.id}: released {n} leftover Browserbase sessions", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"study {study.id}: leftover release failed: {exc!r}", flush=True)

    try:
        asyncio.get_running_loop().create_task(_later())
    except RuntimeError:
        try:
            release_study_sessions(study.id)
        except Exception:
            pass
