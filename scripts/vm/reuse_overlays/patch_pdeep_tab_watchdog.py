#!/usr/bin/env python3
"""Fleet pdeep must honor ph_batch person/tab budgets (orchestrator 2026-11-16).

pdeep.py assigns PB.over_budget = lambda: False, so PH_PERSON_BUDGET_SEC and in-tab
truncated_budget never fire despite patch_person_tab_budget on ph_batch.py.

Captures ph_batch.over_budget at import and delegates; adds PH_TAB_STALL_SECS wall on the
current tab when no GraphQL progress (_tab_progress_t) for idle seconds → requeue person.
"""
from __future__ import annotations

import pathlib
import sys

p = pathlib.Path("/opt/ph/reuse/pdeep.py")
src = p.read_text()
if "PDEEP_TAB_WATCHDOG_PATCH" in src:
    print("pdeep_tab_watchdog already patched")
    sys.exit(0)

needle = '''def _over_budget(R):
    """2140Z audit fix 1: nic() is the whole VM's counter, so with K workers each person would be charged everyone's bytes.
    Charge each person an equal share of the VM's traffic since that person started (per-worker stop-gap)."""
    return False  # 0030Z Shreyas: no per-person budget; only PH limits and the 195e9 weekly stop
PB.over_budget = _over_budget  # module-global lookup: pull()/paging use this from here on'''

repl = '''_pb_person_budget = PB.over_budget  # PDEEP_TAB_WATCHDOG_PATCH: stock ph_batch budget (patched on disk before import)
def _over_budget(R):
    """PDEEP_TAB_WATCHDOG_PATCH: honor PH_PERSON_BUDGET_SEC + per-tab stall (requeue, not a save cap)."""
    try:
        if _pb_person_budget(R):
            return True
    except Exception:
        pass
    try:
        idle = float(os.environ.get("PH_TAB_STALL_SECS", os.environ.get("NO_PROGRESS_SECS", "0")) or 0)
    except Exception:
        idle = 0.0
    if idle <= 0:
        return False
    last = float(getattr(R, "_tab_progress_t", 0) or 0)
    if last <= 0:
        last = float(getattr(R, "t0", 0) or 0)
    if last > 0 and time.time() - last >= idle:
        if not getattr(R, "_tab_stall_budget", False):
            R.log("tab_stall_budget", getattr(R, "_tab_key", "?"), int(idle), "s; requeue person")
            R._tab_stall_budget = True
        return True
    return False
PB.over_budget = _over_budget  # module-global lookup: pull()/paging use this from here on'''

if needle not in src:
    print("_over_budget stub not found in pdeep.py", file=sys.stderr)
    sys.exit(1)
p.write_text(src.replace(needle, repl, 1))
print("patched pdeep_tab_watchdog")