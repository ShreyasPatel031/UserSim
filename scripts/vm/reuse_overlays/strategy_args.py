#!/usr/bin/env python3
"""Map PH_* strategy.env into ph_batch CLI flags (tabs + ramp + person-interval).

Ramp format is tabs:req_per_min tiers (see ph_person.Runner). --tabs is browser
page count (open_browser); ramp can climb logical parallelism / rate independently.
Cap browser pages at PH_BROWSER_TABS (default 32) so e2-standard-2 stays stable.
"""
from __future__ import annotations

import os
import sys


def _i(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def build() -> list[str]:
    strat = (os.environ.get("PH_STRATEGY") or "default").strip()
    max_tabs = max(1, _i("PH_MAX_INFLIGHT_TABS", 5))
    start_tabs = max(1, min(max_tabs, _i("PH_START_INFLIGHT_TABS", min(4, max_tabs))))
    rpm_cap = max(1, _i("PH_REQ_PER_MIN_CAP", 25))
    rpm_start = max(1, min(rpm_cap, _i("PH_START_REQ_PER_MIN", min(45, rpm_cap))))
    coast = max(0, _i("PH_COAST_SEC_PER_PROFILE", 0))
    person_interval = float(os.environ.get("PH_PERSON_INTERVAL") or coast or 0)
    page_cap = max(1, _i("PH_BROWSER_TABS", 32))

    if strat == "ceiling":
        # Explicit parallel-ceiling probe: PH_TABS/PH_RAMP drive open_browser + rate.
        tabs = min(page_cap, max_tabs, _i("PH_TABS", max_tabs))
        ramp = os.environ.get("PH_RAMP") or f"{tabs}:{rpm_cap}"
        person_interval = 0.0
    elif strat == "serial_polite":
        tabs, ramp = 4, "4:36"
        person_interval = person_interval or float(_i("PH_COAST_SEC_PER_PROFILE", 15))
    elif strat == "aimd_adaptive":
        # Open start pages; ramp climbs logical tabs/rate while healthy.
        tabs = min(page_cap, max(start_tabs, min(16, max_tabs)))
        mid = max(start_tabs, min(32, max_tabs))
        ramp = f"{start_tabs}:{rpm_start},{mid}:{max(rpm_start, rpm_cap * 2 // 3)},{max_tabs}:{rpm_cap}"
    elif strat == "burst_coast":
        burst = max(1, min(page_cap, max_tabs, _i("PH_BURST_INFLIGHT_TABS", 24)))
        burst_rpm = max(1, _i("PH_BURST_REQ_PER_MIN", 130))
        tabs, ramp = burst, f"{burst}:{burst_rpm}"
        person_interval = person_interval or float(_i("PH_COAST_SEC", 75))
    elif strat == "req_budget":
        # Keep rate via ramp; open fewer browser pages so CF clear isn't 32-way fanout.
        tabs = min(page_cap, max_tabs, _i("PH_BROWSER_TABS", 8))
        ramp = f"{max_tabs}:{rpm_cap}"
    else:
        tabs = min(page_cap, max_tabs)
        ramp = f"{start_tabs}:{rpm_start},{max_tabs}:{rpm_cap}"

    if os.environ.get("PH_RAMP"):
        ramp = os.environ["PH_RAMP"].strip()
    if os.environ.get("PH_TABS"):
        tabs = _i("PH_TABS", tabs)
    tabs = min(tabs, page_cap)

    args = ["--tabs", str(tabs), "--ramp", ramp]
    if person_interval > 0:
        args += ["--person-interval", str(person_interval)]
    return args


def main() -> None:
    args = build()
    if "--json" in sys.argv:
        import json

        print(json.dumps({"args": args, "strategy": os.environ.get("PH_STRATEGY")}))
    else:
        print(" ".join(args))


if __name__ == "__main__":
    main()
