#!/usr/bin/env python3
"""Re-enable optional per-person wall clock budget (orchestrator 2026-11-16).

Shreyas had disabled over_budget (always False) for nocap whole pulls. Fleet hung on
ProfileFollowersQuery repage (e.g. 220 of 7238) with no progress rows for 15m+.

PH_PERSON_BUDGET_SEC>0: after N seconds on one person, over_budget() fires → tab stops,
truncated_budget/deep_list cursors preserved, person released and retried later (whole pull, not a cap).
PH_PERSON_BUDGET_SEC=0 (default): stock nocap behavior.
"""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/ph_batch.py")
src = p.read_text()
if "PERSON_TAB_BUDGET_PATCH" in src:
    print("person_tab_budget already patched")
    sys.exit(0)

needle = '''def over_budget(R):
    """0030Z Shreyas: no per-person time or byte budget at all. Only PH's own limits and the 195e9 weekly stop end a pull."""
    return False'''

repl = '''def over_budget(R):
    """PERSON_TAB_BUDGET_PATCH: optional per-person time budget (requeue via truncated_budget / deep_list, not a save cap)."""
    try:
        sec = float(os.environ.get("PH_PERSON_BUDGET_SEC", "0") or 0)
    except Exception:
        sec = 0.0
    if sec <= 0:
        return False
    try:
        t0 = float(getattr(R, "t0", 0) or 0)
    except Exception:
        t0 = 0.0
    if t0 <= 0:
        return False
    if time.time() - t0 >= sec:
        if not getattr(R, "_budget_logged", False):
            R.log("person_budget", int(sec), "s; tab stop, requeue later")
            R._budget_logged = True
        return True
    try:
        bmax = float(os.environ.get("PH_PERSON_BUDGET_BYTES", str(BUDGET_BYTES)) or 0)
    except Exception:
        bmax = BUDGET_BYTES
    if bmax > 0 and (nic() - getattr(R, "b0", getattr(R, "b0", 0))) >= bmax:
        return True
    return False'''

if needle not in src:
    print("over_budget stub not found", file=sys.stderr)
    sys.exit(1)
p.write_text(src.replace(needle, repl, 1))
print("patched person_tab_budget")