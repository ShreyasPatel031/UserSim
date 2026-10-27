"""fetchgate: the one way this repo fetches web pages and runs Apify.

    from fetchgate import fetch, run_actor, job_summary
    page = fetch(url)                                   # cheapest route that gets the real page
    page = fetch(url, scroll=True)                      # Camoufox, scrolled to the bottom, XHR/JSON recorded
    items = run_actor(actor, payload)                   # only with ALLOW_APIFY=1

Every attempt is logged (route, bytes, $) and held to the job's budget (FETCH_JOB, default one bucket per day;
cap FETCH_BUDGET_USD, default $5). Never reach a proxy or Apify any other way: the repo scan (fetchgate.scan) fails
the build. Routes, prices and per-site results: docs/discovery/FETCH_LADDER.md.
"""

from __future__ import annotations

from typing import Any

from fetchgate.apify import run_actor
from fetchgate.gate import ApifyNotAllowed, fetch, probe, sample
from fetchgate.ledger import BudgetExceeded, default_job


def job_summary(job: str | None = None) -> dict[str, Any]:
    """Route mix, items, bytes and $ (total and per item) for a job: what to report after a pilot."""
    from fetchgate.gate import remote_url

    job = job or default_job()
    if remote_url():
        from fetchgate import client

        return client.job_summary(job)
    from fetchgate.ledger import ledger

    return ledger().summary(job)


__all__ = ["fetch", "run_actor", "probe", "sample", "job_summary", "BudgetExceeded", "ApifyNotAllowed"]
