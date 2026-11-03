"""Weekly proxy-spend cap for the daily PH refresh (approved: about 700 pages a day, hard cap $1 a week).
    python3 weekly_budget.py YYYY-MM-DD gs://.../raw/ph_people_daily     -> prints the dollars left this week
Exit code 3 when less than MIN_USD is left: run_daily.sh then starts no VM. Each finished day writes <prefix>/<date>/spend.json
({"date", "usd"}) through summarize_daily.py; the cap is the sum over the last 7 days including today (a rerun of the same day counts what
it already spent). A day with no spend.json counts as 0, so a failed day never blocks tomorrow, but a missing ledger entry for a run that did spend would
under-count: summarize_daily.py must run after every VM run.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys

CAP_USD = float(os.environ.get("PHUP_WEEKLY_CAP_USD", "1.0"))
MIN_USD = 0.02  # not worth a VM below this


def remaining(spends: dict[str, float], today: str, cap: float = CAP_USD, days: int = 7) -> float:
    d = dt.date.fromisoformat(today)
    window = {(d - dt.timedelta(days=i)).isoformat() for i in range(days)}
    return max(0.0, round(cap - sum(v for k, v in spends.items() if k in window), 4))


def read_spends(prefix: str, today: str, days: int = 7) -> dict[str, float]:
    d = dt.date.fromisoformat(today)
    out: dict[str, float] = {}
    for i in range(days):
        day = (d - dt.timedelta(days=i)).isoformat()
        r = subprocess.run(["gsutil", "-q", "cat", f"{prefix}/{day}/spend.json"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            out[day] = float(json.loads(r.stdout).get("usd") or 0.0)
    return out


if __name__ == "__main__":
    left = remaining(read_spends(sys.argv[2], sys.argv[1]), sys.argv[1])
    print(left)
    sys.exit(0 if left >= MIN_USD else 3)
