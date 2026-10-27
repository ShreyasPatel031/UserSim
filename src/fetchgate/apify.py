"""Apify actor runs, through the gateway: only with ALLOW_APIFY=1, held to the job's budget, and logged with the cost
Apify reports for the run (usageTotalUsd).

Runs are capped (_RUN_SLOTS) and given explicit memory so parallel scrapes stay under the account limits (16 GB actor
memory, 5 concurrent runs; past either Apify answers HTTP 402). Results come from the run's dataset: sync endpoints are
dropped by long-lived proxies.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from fetchgate import creds
from fetchgate.gate import ApifyNotAllowed, apify_allowed, remote_url
from fetchgate.ledger import default_job, job_cap, ledger

API = "https://api.apify.com/v2"
_RUN_SLOTS = threading.BoundedSemaphore(int(os.environ.get("MVP_APIFY_MAX_RUNS", "3")))
RUN_MEMORY_MB = {"trakk~capterra-reviews-scraper": 2048, "automation-lab~g2-scraper": 256}
DEFAULT_ESTIMATE_USD = 1.0  # held against the budget while a run is going; replaced by the run's reported cost


def run_actor(actor: str, payload: dict[str, Any], *, job: str | None = None, max_cost_usd: float | None = None,
              wait_s: float = 300.0, estimate_usd: float = DEFAULT_ESTIMATE_USD, allow_apify: bool | None = None,
              creds_override: dict[str, str] | None = None, info: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Start an actor run, wait for it, return its dataset items. Raises ApifyNotAllowed without ALLOW_APIFY=1,
    BudgetExceeded when the run's estimate would take the job past its cap, RuntimeError when the run fails.
    info (optional) gets the run's run_id, status and usd."""
    job = job or default_job()
    if remote_url():
        from fetchgate import client

        return client.run_actor(actor, payload, job=job, max_cost_usd=max_cost_usd, wait_s=wait_s,
                                estimate_usd=estimate_usd, allow_apify=apify_allowed(allow_apify),
                                creds_override=creds_override, info=info)
    return _run(actor, payload, job=job, cap=job_cap(max_cost_usd), wait_s=wait_s, estimate_usd=estimate_usd,
                allow_apify=apify_allowed(allow_apify), creds_override=creds_override, info=info)


def _run(actor: str, payload: dict[str, Any], *, job: str, cap: float, wait_s: float, estimate_usd: float,
         allow_apify: bool, creds_override: dict[str, str] | None = None,
         info: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    import requests

    if not allow_apify:
        raise ApifyNotAllowed(f"Apify actor {actor} needs ALLOW_APIFY=1 (ask the founder first)")
    token = creds.apify_token(creds_override)
    if not token:
        raise RuntimeError("no Apify token available to the gateway")
    led = ledger()
    led.reserve(job, estimate_usd, cap)
    t, data, err = time.time(), {}, None
    try:
        with _RUN_SLOTS:
            params: dict[str, Any] = {"token": token}
            if actor in RUN_MEMORY_MB:
                params["memory"] = RUN_MEMORY_MB[actor]
            run = requests.post(f"{API}/acts/{actor}/runs", params=params, json=payload, timeout=60)
            run.raise_for_status()
            data = run.json()["data"]
            deadline = time.monotonic() + wait_s
            while data["status"] in {"READY", "RUNNING"} and time.monotonic() < deadline:
                time.sleep(2)
                data = requests.get(f"{API}/actor-runs/{data['id']}", params={"token": token}, timeout=30).json()["data"]
        if data["status"] != "SUCCEEDED":
            raise RuntimeError(f"{actor} run {data['id']} ended {data['status']}")
        items = requests.get(f"{API}/datasets/{data['defaultDatasetId']}/items",
                             params={"token": token, "clean": "true"}, timeout=120)
        items.raise_for_status()
        return items.json()
    except Exception as exc:  # request errors carry the token in their URL: re-raised without it
        err = creds.redact(repr(exc), token)[:300]
        raise RuntimeError(f"{actor}: {err}") from None
    finally:
        # A run still going at the deadline keeps billing: count the estimate until Apify reports a cost.
        usd = data.get("usageTotalUsd")
        usd = float(usd) if usd is not None and data.get("status") not in {"READY", "RUNNING"} else estimate_usd
        if info is not None:
            info.update(run_id=data.get("id"), status=data.get("status"), usd=round(usd, 6))
        led.record({"job": job, "url": f"actor:{actor}", "route": "apify_actor", "mode": "actor",
                    "status": data.get("status"), "ok": data.get("status") == "SUCCEEDED", "usd": round(usd, 6),
                    "ms": int((time.time() - t) * 1000), "run_id": data.get("id"), "error": err}, reserved=estimate_usd)
