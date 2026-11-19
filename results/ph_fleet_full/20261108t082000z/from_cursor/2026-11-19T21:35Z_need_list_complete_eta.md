# Need-list historical completes — ETA (Shreyas chat authority)

**As of 2026-11-19T21:35Z (~1:35 PM PT)**

## What Population needs

~**1,500 need-list handles** as **complete people** (fleet_work_queue priority **3,471** rows; need-list subset staged in repair/refill). Votes-per-snapshot + upvote **refresh** on slots **9/27/38** stay as today (~**1.0 refresh/min** fleet-wide in 15m window).

## Why complete_ppm still looks like “refresh only”

| Issue | Status |
|--------|--------|
| Unpark (20:30Z) | **20/20 RUNNING**, 20 unique IPRoyal hosts |
| **Blocker (fixed ~21:02Z)** | Bad `ph-strategy-env` metadata (path string not file body) → phsuper could not load strategy on **12 unparked slots** |
| After fix | Brief **slot 5** completes (~1.1 fleet complete_ppm at 21:15Z), then window slid back; **0 historical slots** with `win_complete>0` in latest 15m measure |
| Now | **6** historical VMs show `batch` up but **stale/dead** in measure; **8 dead**, rest stale/cf_wall — pulling or hung, **not** landing Population **whole()** completes yet |
| **Not** | Live hold (`critical_stale=false`), freeze, or VM park |

## First need-list **complete** people — fleet-cursor estimate

| Milestone | ETA (PT) | Basis |
|-----------|----------|--------|
| **First 1–3 need-list completes** land in Population store | **~2:00–3:00 PM PT** (21:00–23:00Z) | Finish stale-unhang / phsuper boot on **13, 36, 29–30, 40**; **1–2** slots at ~0.2–0.3 complete/min each |
| **Sustained historical complete_ppm ≥ 5** (mix refresh + pdeep) | **~3:30–6:00 PM PT** | Need **≥8** historical slots steady (target **12+** of 16 pdeep); ~0.4/min/slot × 12 ≈ **5+** incremental on top of refresh |
| **~1,500 need-list completes** | **~3–5 days** at **5–10** historical complete/min average | Queue already seeded (`fleet_work_queue.txt`, refill **1440** work handles / 16 slots); dominated by CF/429 backoff per sticky IP, not missing queue |

**Earlier than 2 PM PT** only if **slot 28** (pilot) or **13/36** post-unhang shows `win_complete` in the **next 15m** tick — we are watching those three, not mass-restarting.

## Ops next (no park, no orchestrator scale commands)

1. Continue **single-slot** stale-unhang / keeper nudge on **stale >30m** dead or hung (already **13, 36** this hour).
2. **No** recreate; **no** `-rN` GO; keeper `NUDGE_GO=0`.
3. Update this file when **first** historical `win_complete` appears on any slot **≠ 9/27/38**.

**Relay:** ACK orchestrator 21:33Z with this ETA; historical scale **allowed** (not `LIVE_PRIORITY_HOLD`).