# Upvote refresh resume — orchestrator 20:34Z

**Question:** `status.json` @ **20:32Z** shows `upvote_refresh_ppm_15m=0` and `complete_ppm=0` (16 dead slots incl. **9/27/38**). Is this the interval-fix / exit-IP roll? When does refresh resume and at what rate?

## Not the exit-IP roll

| Fact | Detail |
|------|--------|
| **exit-IP light roll (~12:00–12:02 PT)** | Overlays + heartbeat only; **no `phsuper` stop** on refresh slots |
| **Refresh stopped ~19:52Z** | Last upvote-save rows on **9/27/38** at **19:51:29–19:51:55Z**; then **`phsuper` inactive** (supervisor exited; batch not running) |
| **Historical dead slots** | CF / browser-open failures on **pdeep** (unchanged) |

**Root cause @ 20:32Z:** refresh VMs were **up** but **supervisor not running**, not PH-wide block on 9/27/38.

## Actions taken (20:35–20:37Z PT)

1. **In-place `phsuper` restart** on **9, 27, 38** (`ph_fleet_inplace_restart_slots.sh`) with existing `repullupvotes:fleet-upvote-20261108t082000z-20261120T0834Z` GO.
2. **`patch_repullupvotes_person_interval.py`** applied on **9/27/38** (was **not** on disk before restart — explains prior **~3 min/person** pacing).
3. **LIVE_PRIORITY_HOLD** — no historical fleet scale-up.

## When refresh resumes

| Milestone | Time (PT) | Signal |
|-----------|-----------|--------|
| Supervisor active + batch launch | **~12:35 PT** (20:35Z) | `phsuper` **active** on **9**; `exit_ip_resume` on launch |
| First refreshed saves in 15m window | **~12:40–12:50 PT** | `upvote_refresh_ppm_15m` > 0 in `status.json` |
| Steady recent-voter refresh (post patch) | **~12:45 PT onward** | Sustained saves on **9/27/38** status logs |

## Expected rate (recent-voter refresh, 3 slots)

| Regime | `upvote_refresh_ppm_15m` (fleet) | Per slot (~) |
|--------|----------------------------------|--------------|
| **Before interval fix** (through 19:52Z) | **~1.0** | **~20 saves/h** (~180s gap + ~20s read) |
| **After interval fix** (target, `PH_PERSON_INTERVAL=0`) | **~3–6** | **~60–120 saves/h** (~20–40s/person) |
| **After diff early-stop ships** (not yet) | **higher** | More people/h when `items_added=0` stops at page 1 |

**Coverage priority:** queue unchanged (**4,803**); refresh slots pull **`refresh_priority_*`** via repullupvotes GO. Population staging should see new `shared/*.json` within **~15–30 min** of **12:35 PT** restart if saves land.

## Still open

- **Diff early-stop** on upvotes chain (8–10 pages with `items_added=0`) — ETA in tier-1 doc (**~Nov 26 PT** commit path).
- **+5 refresh slots** for tier-(1) coverage — not started (hold).

**Artifacts:** `refresh_restart_2035.log`, `2026-11-20T19:30Z_upvote_refresh_timing_sample.md`, commit **`046b8325`** (`ads`).