"""The spend log and the budget: every fetch attempt is one JSON line (route, bytes, estimated $), and a job stops
with BudgetExceeded before an attempt that would take its total past the cap.

Caps (US dollars):
  per job    5 by default. A caller can lower it (max_cost_usd); raising it needs FETCH_BUDGET_USD in the caller's
             environment, and the gateway service clamps whatever it is sent to FETCHGATE_MAX_JOB_USD (default 50).
  per day    FETCHGATE_DAILY_USD (default 25), all jobs together, so new job names cannot get around the job cap.

Before a paid attempt its worst-case cost is reserved; afterwards the reservation is replaced by the measured cost.
Totals are rebuilt from the log when a process starts, so they survive restarts. Log: FETCHGATE_LOG, default
/var/log/fetchgate/fetches.jsonl when writable, else ~/.cache/fetchgate/fetches.jsonl.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

DEFAULT_JOB_USD = 5.0


class BudgetExceeded(RuntimeError):
    """The next attempt would take the job (or today's total) past its cap. Stop the job and ask before raising it."""


def _num(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def job_cap(requested: float | None = None) -> float:
    """The cap for a job run by this process: FETCH_BUDGET_USD (default 5), or less when the caller asks for less."""
    ceiling = _num("FETCH_BUDGET_USD", DEFAULT_JOB_USD)
    return ceiling if requested is None else min(float(requested), ceiling)


def daily_cap() -> float:
    return _num("FETCHGATE_DAILY_USD", 25.0)


def default_job() -> str:
    """FETCH_JOB, else one shared bucket per day: unnamed jobs together never pass the default cap."""
    return (os.environ.get("FETCH_JOB") or "").strip() or f"adhoc-{dt.date.today().isoformat()}"


def _default_path() -> Path:
    if os.environ.get("FETCHGATE_LOG"):
        return Path(os.environ["FETCHGATE_LOG"])
    sys_dir = Path("/var/log/fetchgate")
    if sys_dir.is_dir() and os.access(sys_dir, os.W_OK):
        return sys_dir / "fetches.jsonl"
    return Path.home() / ".cache" / "fetchgate" / "fetches.jsonl"


class Ledger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _default_path()
        self._lock = threading.Lock()
        self._jobs: dict[str, float] = {}
        self._days: dict[str, float] = {}
        self._pending: dict[str, float] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            with open(self.path) as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    usd = float(row.get("usd") or 0)
                    if usd:
                        self._jobs[row.get("job", "")] = self._jobs.get(row.get("job", ""), 0.0) + usd
                        day = str(row.get("ts", ""))[:10]
                        self._days[day] = self._days.get(day, 0.0) + usd
        except OSError:
            pass

    def spent(self, job: str) -> float:
        with self._lock:
            self._load()
            return self._jobs.get(job, 0.0)

    def today(self) -> float:
        with self._lock:
            self._load()
            return self._days.get(dt.datetime.now(dt.timezone.utc).date().isoformat(), 0.0)

    def reserve(self, job: str, estimate: float, cap: float) -> str:
        """Hold estimate against the job and today's totals; BudgetExceeded when either would pass its cap."""
        day = dt.datetime.now(dt.timezone.utc).date().isoformat()
        with self._lock:
            self._load()
            held = self._pending.get(job, 0.0)
            held_all = sum(self._pending.values())
            job_total = self._jobs.get(job, 0.0) + held + estimate
            day_total = self._days.get(day, 0.0) + held_all + estimate
            if estimate and job_total > cap:
                raise BudgetExceeded(f"job {job!r}: ${self._jobs.get(job, 0.0) + held:.4f} spent, the next attempt "
                                     f"(up to ${estimate:.4f}) would pass its ${cap:.2f} cap. Report the route mix and "
                                     f"$ per item, and ask the founder before raising FETCH_BUDGET_USD.")
            if estimate and day_total > daily_cap():
                raise BudgetExceeded(f"today's fetch spend ${self._days.get(day, 0.0) + held_all:.4f} plus the next "
                                     f"attempt (up to ${estimate:.4f}) would pass the ${daily_cap():.2f} daily cap "
                                     f"(FETCHGATE_DAILY_USD). Ask the founder.")
            self._pending[job] = held + estimate
            return day

    def record(self, row: dict[str, Any], *, reserved: float = 0.0) -> dict[str, Any]:
        """Append one attempt to the log and add its cost to the totals (releasing what was reserved for it)."""
        row = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")} | row
        usd = float(row.get("usd") or 0)
        job = row.get("job", "")
        with self._lock:
            self._load()
            if reserved:
                self._pending[job] = max(0.0, self._pending.get(job, 0.0) - reserved)
                if not self._pending[job]:
                    self._pending.pop(job)
            if usd:
                self._jobs[job] = self._jobs.get(job, 0.0) + usd
                self._days[row["ts"][:10]] = self._days.get(row["ts"][:10], 0.0) + usd
            row["job_usd"] = round(self._jobs.get(job, 0.0), 6)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a") as f:  # append-only
                    f.write(json.dumps(row) + "\n")
            except OSError as exc:  # a fetch whose cost cannot be logged must not run unlogged next time
                raise RuntimeError(f"fetchgate: cannot write the spend log {self.path}: {exc}") from exc
        return row

    def summary(self, job: str) -> dict[str, Any]:
        """Route mix, pages, bytes and dollars for one job (read back from the log)."""
        routes: dict[str, dict[str, float]] = {}
        items = 0
        try:
            with open(self.path) as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if row.get("job") != job:
                        continue
                    r = routes.setdefault(row.get("route") or "?", {"attempts": 0, "passed": 0, "bytes": 0, "usd": 0.0})
                    r["attempts"] += 1
                    r["passed"] += 1 if row.get("ok") else 0
                    r["bytes"] += int(row.get("bytes") or 0)
                    r["usd"] = round(r["usd"] + float(row.get("usd") or 0), 6)
                    items += 1 if row.get("ok") else 0
        except OSError:
            pass
        total = round(sum(r["usd"] for r in routes.values()), 6)
        return {"job": job, "items_fetched": items, "usd": total,
                "usd_per_item": round(total / items, 6) if items else None, "routes": routes,
                "cap_usd": job_cap(), "today_usd": round(self.today(), 6), "daily_cap_usd": daily_cap(),
                "log": str(self.path), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


_LEDGER: Ledger | None = None
_LEDGER_LOCK = threading.Lock()


def ledger() -> Ledger:
    global _LEDGER
    with _LEDGER_LOCK:
        if _LEDGER is None:
            _LEDGER = Ledger()
        return _LEDGER


def set_ledger(new: Ledger | None) -> None:
    """Tests: point the gateway at another log."""
    global _LEDGER
    with _LEDGER_LOCK:
        _LEDGER = new
