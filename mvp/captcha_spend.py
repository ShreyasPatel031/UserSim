"""CapSolver experiment budget.

The key is read only from ``CAPSOLVER_API_KEY``. This module never logs it.

Hard stops, enforced before every ``createTask``:

- live balance must stay at or above $1.00 (spend the rest of the balance)
- outside experiment mode, $19 booked on the ledger is a second brake
- outside experiment mode, 3 solves per signup attempt
- outside experiment mode, 20 signup attempts per site

``MVP_CAPTCHA_EXPERIMENT=1`` lifts the per-attempt, per-site, and ledger-total
brakes so a type survey can run until the live balance would drop below $1.
The per-site dollar cap stays lifted. Only task types on CapSolver's published
price list (docs.capsolver.com/en/pricing/ and the task pages, 2026-09-26)
are sent. hCaptcha and FunCaptcha are not on that list. FunCaptcha may be
probed once when experiment mode is on; a rejected probe is not retried.
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# USD per solve from https://docs.capsolver.com/en/pricing/ (per 1,000 tokens).
# Task names are the ones on the official task pages (2026-09-26).
PRICED_TASKS_USD: dict[str, float] = {
    "ReCaptchaV2TaskProxyLess": 0.80 / 1000,
    "ReCaptchaV2EnterpriseTaskProxyLess": 1.00 / 1000,
    "ReCaptchaV3TaskProxyLess": 1.00 / 1000,
    "ReCaptchaV3EnterpriseTaskProxyLess": 3.00 / 1000,
    "AntiTurnstileTaskProxyLess": 1.20 / 1000,
    "AntiCloudflareTask": 1.20 / 1000,
    "GeeTestTaskProxyLess": 1.20 / 1000,
    "MtCaptchaTaskProxyLess": 3.00 / 1000,
    "AntiAwsWafTaskProxyLess": 2.00 / 1000,
    "ReCaptchaV2Classification": 0.40 / 1000,
    "AwsWafClassification": 0.60 / 1000,
    "ImageToTextTask": 0.40 / 1000,
    "DatadomeSliderTask": 2.50 / 1000,
}

# Not on the official support or price list. One createTask, then stop.
PROBE_TASKS_USD: dict[str, float] = {
    "FunCaptchaTaskProxyLess": 0.02,
}
MAX_PROBES_PER_TASK = 1

# Live getBalance must not fall below this. Ledger cap is the second brake.
BALANCE_FLOOR_USD = 1.0
TOTAL_CAP_USD = 19.0
MAX_SOLVES_PER_ATTEMPT = 3
MAX_SIGNUP_ATTEMPTS = 20

_LOCK = threading.Lock()
_INFLIGHT_USD = 0.0
_SITE: ContextVar[str] = ContextVar("captcha_spend_site", default="")
_ATTEMPT: ContextVar[int] = ContextVar("captcha_spend_attempt", default=0)
_LAST = threading.local()


class SpendCapError(RuntimeError):
    pass


def ledger_path() -> Path:
    raw = (os.environ.get("CAPTCHA_SPEND_LEDGER") or "").strip()
    if raw:
        return Path(raw)
    return ROOT / "results" / "captcha_spend" / "ledger.jsonl"


def capsolver_key() -> str:
    """Research key. Env only — never the vault, never a log line."""
    return (os.environ.get("CAPSOLVER_API_KEY") or "").strip()


def paid_hosts() -> set[str]:
    raw = os.environ.get("MVP_CAPTCHA_PAID_HOSTS") or ""
    return {h.strip().lower().removeprefix("www.") for h in raw.split(",") if h.strip()}


def experiment_mode() -> bool:
    return (os.environ.get("MVP_CAPTCHA_EXPERIMENT") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def policy_path() -> Path:
    raw = (os.environ.get("CAPTCHA_METHOD_POLICY") or "").strip()
    if raw:
        return Path(raw)
    return ROOT / "results" / "captcha_spend" / "method_policy.json"


def load_method_policy() -> dict[str, Any]:
    path = policy_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def endorsed_task(task_type: str) -> bool:
    """True when the published signup policy says this task is worth paying for."""
    policy = load_method_policy()
    if not policy.get("apply_to_signup"):
        return False
    types = policy.get("types") or {}
    if not isinstance(types, dict):
        return False
    for spec in types.values():
        if not isinstance(spec, dict):
            continue
        if spec.get("task") == task_type and spec.get("method") in {
            "capsolver",
            "image_to_text",
            "recaptcha_classification",
            "capsolver_v2_enterprise",
        }:
            return True
    return False


def reset_runtime_state() -> None:
    """Clear the in-process reserve. Tests and a fresh experiment call this."""
    global _INFLIGHT_USD
    with _LOCK:
        _INFLIGHT_USD = 0.0


def task_price(task_type: str) -> float | None:
    if task_type in PRICED_TASKS_USD:
        return PRICED_TASKS_USD[task_type]
    if (
        task_type in PROBE_TASKS_USD
        and experiment_mode()
        and probe_count(task_type) < MAX_PROBES_PER_TASK
    ):
        return PROBE_TASKS_USD[task_type]
    return None


def probe_count(task_type: str) -> int:
    return sum(
        1
        for row in _read_rows()
        if row.get("event") == "createTask" and row.get("task_type") == task_type
    )


def host_allowed(host: str) -> bool:
    host = (host or "").strip().lower().removeprefix("www.")
    if not host:
        return False
    if experiment_mode():
        return True
    allowed = paid_hosts()
    if "*" in allowed or "all" in allowed:
        return True
    return host in allowed


def bind_signup(site: str, attempt: int) -> None:
    _SITE.set((site or "").strip().lower().removeprefix("www."))
    _ATTEMPT.set(int(attempt))


def current_site() -> str:
    return _SITE.get() or ""


def current_attempt() -> int:
    return int(_ATTEMPT.get() or 0)


def remember_outcome(**fields: Any) -> None:
    """Thread-local result of the solve that just finished. Never stores the key."""
    _LAST.outcome = {
        k: v for k, v in fields.items() if str(k).lower() not in {"clientkey", "api_key", "key"}
    }


def last_outcome() -> dict[str, Any]:
    raw = getattr(_LAST, "outcome", None)
    return dict(raw) if isinstance(raw, dict) else {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_rows() -> list[dict[str, Any]]:
    path = ledger_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _append(row: dict[str, Any]) -> None:
    # Drop anything that could carry the key if a caller passes a response blob.
    clean = {k: v for k, v in row.items() if k.lower() not in {"clientkey", "api_key", "key"}}
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a") as fh:
            fh.write(json.dumps(clean, sort_keys=True) + "\n")


def signup_attempts(site: str) -> int:
    site = (site or "").strip().lower()
    return sum(
        1
        for row in _read_rows()
        if row.get("event") == "signup_start" and row.get("site") == site
    )


def solves_for_attempt(site: str, attempt: int) -> int:
    return sum(
        1
        for row in _read_rows()
        if row.get("event") == "createTask"
        and row.get("site") == site
        and int(row.get("attempt") or 0) == int(attempt)
    )


def spent_usd(*, site: str | None = None) -> float:
    total = 0.0
    for row in _read_rows():
        if row.get("event") != "createTask":
            continue
        if site is not None and row.get("site") != site:
            continue
        try:
            total += float(row.get("cost") or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 6)


def begin_signup_attempt(site: str) -> int:
    """Record one fresh-alias signup.

    Outside experiment mode this refuses attempt 21. Experiment mode keeps
    going until the live balance floor.
    """
    host = (site or "").strip().lower().removeprefix("www.")
    if not host:
        raise SpendCapError("signup attempt missing site")
    n = signup_attempts(host)
    if n >= MAX_SIGNUP_ATTEMPTS and not experiment_mode():
        raise SpendCapError(
            f"signup cap: {host} already has {n} attempts (max {MAX_SIGNUP_ATTEMPTS})"
        )
    attempt = n + 1
    _append({"event": "signup_start", "site": host, "attempt": attempt, "ts": _now()})
    bind_signup(host, attempt)
    return attempt


def ensure_attempt(site: str) -> int:
    """Bind a signup attempt, reusing the latest one during the experiment."""
    host = (site or "").strip().lower().removeprefix("www.")
    n = signup_attempts(host)
    if experiment_mode() and n >= 1:
        bind_signup(host, n)
        return n
    return begin_signup_attempt(host)


def refusal_reason(task_type: str, *, site: str | None = None, attempt: int | None = None) -> str | None:
    """Why createTask must not be called, or None if the ledger allows it.

    The live $1 balance floor is applied separately by ``claim_spend`` after
    ``getBalance``, so a refusal here never needs an HTTP call.
    """
    host = (site if site is not None else current_site()).strip().lower().removeprefix("www.")
    att = current_attempt() if attempt is None else int(attempt)
    if not host_allowed(host) and not endorsed_task(task_type):
        return "host_not_paid"
    if att < 1:
        return "no_signup_attempt"
    price = task_price(task_type)
    if price is None:
        return "unsupported_or_unpriced"
    # Experiment mode spends until the live $1 floor. The attempt and ledger
    # brakes stay on for ordinary signup so a bug cannot drain the balance.
    if experiment_mode():
        return None
    if solves_for_attempt(host, att) >= MAX_SOLVES_PER_ATTEMPT:
        return "solve_attempt_cap"
    if spent_usd() >= TOTAL_CAP_USD:
        return "total_cap"
    if spent_usd() + price > TOTAL_CAP_USD + 1e-9:
        return "total_cap"
    return None


def claim_spend(task_type: str, balance: float | None) -> str | None:
    """Reserve list price against the live balance. None means createTask may run."""
    global _INFLIGHT_USD
    price = task_price(task_type)
    if price is None:
        return "unsupported_or_unpriced"
    try:
        bal = None if balance is None else float(balance)
    except (TypeError, ValueError):
        bal = None
    with _LOCK:
        if bal is None:
            return "balance_unknown"
        if bal - _INFLIGHT_USD - price < BALANCE_FLOOR_USD - 1e-9:
            return "balance_floor"
        _INFLIGHT_USD = round(_INFLIGHT_USD + price, 6)
    return None


def release_spend(task_type: str) -> None:
    """Drop a reserve taken by ``claim_spend`` (call once after the task settles)."""
    global _INFLIGHT_USD
    price = task_price(task_type) or 0.0
    with _LOCK:
        _INFLIGHT_USD = round(max(0.0, _INFLIGHT_USD - price), 6)


def get_balance(key: str | None = None) -> float | None:
    """CapSolver getBalance. Returns USD or None. Does not log the key."""
    import httpx

    token = key if key is not None else capsolver_key()
    if not token:
        return None
    for attempt in range(3):
        try:
            payload = httpx.post(
                "https://api.capsolver.com/getBalance",
                json={"clientKey": token},
                timeout=20.0,
            ).json()
        except Exception:
            time.sleep(0.4 * (attempt + 1))
            continue
        if not isinstance(payload, dict) or payload.get("errorId"):
            time.sleep(0.4 * (attempt + 1))
            continue
        try:
            return round(float(payload.get("balance")), 6)
        except (TypeError, ValueError):
            return None
    return None


def record_balance(site: str, *, when: str) -> float | None:
    balance = get_balance()
    _append(
        {
            "event": "balance",
            "site": site,
            "when": when,
            "balance": balance,
            "attempt": current_attempt(),
            "ts": _now(),
        }
    )
    return balance


def record_task(
    *,
    site: str,
    captcha_type: str,
    task_type: str,
    task_id: str | None,
    solved: bool,
    cost: float | None,
    balance_before: float | None,
    balance_after: float | None,
    note: str = "",
) -> None:
    delta = None
    if balance_before is not None and balance_after is not None:
        try:
            delta = round(max(0.0, float(balance_before) - float(balance_after)), 6)
        except (TypeError, ValueError):
            delta = None
    _append(
        {
            "event": "createTask",
            "site": site,
            "captcha_type": captcha_type,
            "task_type": task_type,
            "task_id": task_id,
            "solved": bool(solved),
            "cost": None if cost is None else round(float(cost), 6),
            "list_price": task_price(task_type),
            "balance_before": balance_before,
            "balance_after": balance_after,
            "balance_delta": delta,
            "attempt": current_attempt(),
            "note": note[:200],
            "ts": _now(),
        }
    )
    remember_outcome(
        event="createTask",
        site=site,
        captcha_type=captcha_type,
        task_type=task_type,
        solved=bool(solved),
        cost=None if cost is None else round(float(cost), 6),
        note=note[:200],
    )


def record_skip(*, site: str, captcha_type: str, task_type: str, reason: str) -> None:
    _append(
        {
            "event": "skip",
            "site": site,
            "captcha_type": captcha_type,
            "task_type": task_type,
            "reason": reason,
            "attempt": current_attempt(),
            "ts": _now(),
        }
    )
    remember_outcome(
        event="skip",
        site=site,
        captcha_type=captcha_type,
        task_type=task_type,
        solved=False,
        cost=0.0,
        note=reason[:200],
        reason=reason,
    )
