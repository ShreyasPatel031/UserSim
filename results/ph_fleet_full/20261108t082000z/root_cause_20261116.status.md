# Fleet root cause — 2026-11-16 05:35Z

## Slot studied

**feeder-fleet-20261108t082000z-28** (stale, batch alive, 507-line `pdeep_list`, not list exhaustion).

## Cause A — blind stale_unhang (ops)

`fleet-fix-2m` + `ph_fleet_utilization_recover.sh` ran **stale_unhang every ~2m** on slots with `win_complete=0` and `age≥600s`. That **SIGKILLs `pdeep`/Camoufox** mid-pull.

Evidence: `run_20261116T0521Z.log` shows active **ProfileFollowersQuery repage 220/7238** until **05:26Z**; supervisor relaunched at **05:27Z** with a new recover token → cycle **pdeep_test_list → browser_open → exit_ip** every ~3 min, **no handle rows** (ppm ~0 from that slot).

**Fix:** `FLEET_STALE_AGE_SEC` default **2400**; skip unhang when run log **mtime &lt;12m** and tail has **paged/repage/op_seen** (`stale_skip_active_pull`).

## Cause B — huge follow tab (code)

When unhang did not interrupt, slot 28 hung on **ProfileFollowersQuery** offset **repage** (`220 of 7238` followers). `over_budget()` was hardcoded **False** (nocap), so **NO_PROGRESS_SECS=600** only helps if **zero** gql movement — repage still advances slowly.

**Fix:** `patch_person_tab_budget.py` + `PH_PERSON_BUDGET_SEC=1080` / `NO_PROGRESS_SECS=300` in `fleet_iproyal.env` → tab stops, **deep_list cursors**, person **requeued** (not saved as whole).

## Not the cause

- Empty list (GCS + local **507** lines; `pdeep_test_list` n=507).
- Sign-in wall / CF on slot 28 (exit_ip stable TR AS56582).
- IP rotation (none).