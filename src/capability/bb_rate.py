"""One process-wide limiter for Browserbase session creates.

Browserbase caps session CREATION at 25 requests per rolling minute per
project ("You've exceeded your burst rate limit (25 requests per 1 minute).
You can try again in 34 seconds."). The general API limit (6000/min) is not
the problem. A 24-agent study used to send all its creates in ~14s, so any
retry, signup, second study, or hygiene create in that minute got a 429.
That surfaced as a create timeout and a dropped agent.

Every HTTP session-create in this process takes a token here first:

* at most ``capacity`` creates (default 22) in any rolling ``window_s`` (60s),
  leaving a margin under 25 for hygiene or manual calls;
* waiters are served by priority (0 = product agents, 1 = default, 2 = rivals),
  then first come, first served;
* a 429 blocks every grant until the "try again in N seconds" moment plus
  jitter, and the caller retries the same create instead of failing.

It is thread-safe because ``create_session`` is synchronous and runs in worker
threads (``asyncio.to_thread``); ``acquire_async`` is the event-loop wrapper.
The clock and sleep are injectable so tests run on a fake clock.
"""
from __future__ import annotations

import asyncio
import collections
import heapq
import itertools
import os
import random
import re
import threading
import time
from typing import Any, Callable

PRIORITY_PRODUCT = 0
PRIORITY_DEFAULT = 1
PRIORITY_RIVAL = 2


class BucketTimeout(TimeoutError):
    """No create token before the caller's deadline (or the caller cancelled)."""


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


class CreateBucket:
    def __init__(
        self,
        capacity: int = 22,
        window_s: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] | None = None,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        self.capacity = max(1, int(capacity))
        self.window_s = float(window_s)
        self._clock = clock
        self._sleep = sleep  # None: real Condition.wait, woken by grants
        self._jitter = jitter or (lambda: random.uniform(0.5, 2.5))
        self._cond = threading.Condition()
        self._grants: collections.deque[float] = collections.deque()
        self._waiters: list[tuple[int, int]] = []
        self._seq = itertools.count()
        self.blocked_until = 0.0
        self.stats = {"granted": 0, "rate_limited": 0, "max_wait_s": 0.0}

    # ---- inspection (lock-free callers get a consistent-enough view) ----
    def _prune(self, now: float) -> None:
        edge = now - self.window_s
        while self._grants and self._grants[0] <= edge:
            self._grants.popleft()

    def recent(self, now: float | None = None) -> int:
        """Creates granted in the last window."""
        with self._cond:
            now = self._clock() if now is None else now
            self._prune(now)
            return len(self._grants)

    def room_in(self, n: int = 1, now: float | None = None) -> float:
        """Seconds until at least ``n`` tokens are free (0 when free now)."""
        with self._cond:
            now = self._clock() if now is None else now
            return self._room_in_locked(n, now)

    def _room_in_locked(self, n: int, now: float) -> float:
        self._prune(now)
        n = max(1, min(int(n), self.capacity))
        wait = max(0.0, self.blocked_until - now)
        over = len(self._grants) + n - self.capacity
        if over > 0:
            # The over-th oldest grant must age out of the window.
            wait = max(wait, self._grants[over - 1] + self.window_s - now)
        return wait

    def waiting(self) -> int:
        with self._cond:
            return len(self._waiters)

    # ---- feedback from Browserbase ----
    def note_rate_limited(self, retry_after_s: float | None, now: float | None = None) -> float:
        """A 429 arrived: hold every grant until the server's retry moment plus jitter.

        Returns the moment (clock units) grants resume.
        """
        with self._cond:
            now = self._clock() if now is None else now
            wait = retry_after_s if retry_after_s is not None and retry_after_s >= 0 else self.window_s / 2
            until = now + float(wait) + max(0.0, float(self._jitter()))
            self.blocked_until = max(self.blocked_until, until)
            self.stats["rate_limited"] += 1
            self._cond.notify_all()
            return self.blocked_until

    # ---- tokens ----
    def acquire(
        self,
        priority: int = PRIORITY_DEFAULT,
        *,
        deadline: float | None = None,
        cancel: threading.Event | None = None,
        on_wait: Callable[[float, str], None] | None = None,
    ) -> float:
        """Block until this create may be sent. Returns seconds waited.

        ``deadline`` is in this bucket's clock units. Raises BucketTimeout when
        the token cannot arrive by then or ``cancel`` is set.
        """
        start = self._clock()
        me = (int(priority), next(self._seq))
        announced = -1.0
        with self._cond:
            heapq.heappush(self._waiters, me)
            try:
                while True:
                    now = self._clock()
                    if cancel is not None and cancel.is_set():
                        raise BucketTimeout("create cancelled while waiting for a Browserbase token")
                    head = self._waiters[0] == me
                    wait = self._room_in_locked(1, now)
                    if head and wait <= 0:
                        heapq.heappop(self._waiters)
                        self._grants.append(now)
                        self.stats["granted"] += 1
                        waited = now - start
                        self.stats["max_wait_s"] = max(self.stats["max_wait_s"], waited)
                        self._cond.notify_all()
                        return waited
                    if deadline is not None and now + (wait if head else 0.0) > deadline:
                        raise BucketTimeout(
                            f"no Browserbase create token within the deadline (needs ~{wait:.0f}s more)"
                        )
                    if not head:
                        # Behind a higher-priority or earlier waiter: its grant wakes us.
                        wait = max(wait, 0.25)
                    if on_wait is not None and (announced < 0 or abs(announced - wait) >= 5):
                        announced = wait
                        reason = "burst limit" if self.blocked_until > now else "create budget"
                        try:
                            on_wait(wait, reason)
                        except Exception:
                            pass
                    step = min(wait, 1.0) if cancel is not None else wait
                    if deadline is not None:
                        step = min(step, max(0.01, deadline - now))
                    step = max(0.01, step)
                    if self._sleep is None:
                        self._cond.wait(timeout=step)
                    else:
                        self._cond.release()
                        try:
                            self._sleep(step)
                        finally:
                            self._cond.acquire()
            finally:
                try:
                    self._waiters.remove(me)
                    heapq.heapify(self._waiters)
                except ValueError:
                    pass
                self._cond.notify_all()

    async def acquire_async(self, priority: int = PRIORITY_DEFAULT, **kw: Any) -> float:
        return await asyncio.to_thread(self.acquire, priority, **kw)


_RETRY_RES = (
    re.compile(r"try again in\s+(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|secs?|seconds?|m|mins?|minutes?)\b", re.I),
    re.compile(r"retry[-_ ]after[\"'\s:=]+(\d+(?:\.\d+)?)", re.I),
)


def parse_retry_after(obj: Any) -> float | None:
    """Seconds a 429 asks us to wait, from the body text or a Retry-After header."""
    resp = getattr(obj, "response", None)
    headers = getattr(resp, "headers", None)
    if headers is not None:
        try:
            raw = headers.get("retry-after-ms")
            if raw:
                return max(0.0, float(raw) / 1000.0)
            raw = headers.get("retry-after")
            if raw:
                return max(0.0, float(raw))
        except (TypeError, ValueError):
            pass
    parts = [str(obj)]
    body = getattr(obj, "body", None)
    if body is not None:
        parts.append(str(body))
    text = " ".join(parts)
    m = _RETRY_RES[0].search(text)
    if m:
        val = float(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("ms") or unit.startswith("milli"):
            return val / 1000.0
        if unit.startswith("m"):
            return val * 60.0
        return val
    m = _RETRY_RES[1].search(text)
    if m:
        return float(m.group(1))
    return None


def is_burst_limit(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    msg = str(exc).lower()
    return "429" in msg or "burst rate limit" in msg or "too many requests" in msg or "rate limit" in msg


_BUCKET: CreateBucket | None = None
_BUCKET_LOCK = threading.Lock()


def create_bucket() -> CreateBucket:
    """The process-wide bucket (BROWSERBASE_CREATE_BURST / _WINDOW_S override 22 / 60)."""
    global _BUCKET
    with _BUCKET_LOCK:
        if _BUCKET is None:
            cap = int(_env_float("BROWSERBASE_CREATE_BURST", 22))
            _BUCKET = CreateBucket(capacity=max(1, min(25, cap)), window_s=_env_float("BROWSERBASE_CREATE_WINDOW_S", 60.0))
        return _BUCKET


def recent_creates() -> int:
    return create_bucket().recent()
