# Need-list complete ETA — revision 2 (2026-11-19T23:35Z / ~3:35 PM PT)

**Supersedes:** `2026-11-19T21:35Z_need_list_complete_eta.md` (23:00Z first-complete window **missed** — acknowledged to orchestrator).

## Status at 23:32Z

| Metric | Value |
|--------|--------|
| Fleet complete_ppm | **~0.87–1.0/min** (15m window) — **all refresh** (slots 9, 27, 38) |
| Historical slots **active** in measure | **0** (13× stale, 2× dead; many show `batch` but **0 `win_complete`**) |
| Population store COMPLETE | **93,401** — last cycles **re-saves only**, no new need-list wholes |
| VMs / IPs | **20/20 RUNNING**, **20** unique IPRoyal hosts |
| Live | **not** `critical_stale` |

## Why 23:00Z ETA slipped

1. **~21:02Z** — Unpark **`ph-strategy-env` bug** (path string, not file body) blocked **12** slots until metadata fix; cost **~1 h** ramp.
2. **Pilot care works, then re-poisons** — Slots **28** / **13** got `pdeep_test_list n=90 skipped_done=0` after care, but within **~30 min** supervisor returns to **`same_tok_retry`** on the **same pilot GO** → **`n=0 skipped_done=90`** and **43-byte** `FINGERPRINT_REUSED` fast exits (slot **28** tail at **23:34Z**). Same class as morning **`pdeep_tried` / token-retry storm**; measure marks slots **stale** while phsuper spins.
3. **Recover path** — `utilization_recover` stale-unhang uses tokens like `recover-*` but does not always clear **`pdeep_tried.json`** before relaunch; **`wakeup n=0`** on dead slots where batch probe fails.

**Not:** missing queue (refill **~1,438** work handles / 16 slots), live hold, or fleet park.

## Updated ETAs (~1,500 need-list complete people)

| Milestone | Revised ETA (PT) | Notes |
|-----------|-------------------|--------|
| **First 1–3 new need-list completes** in Population (not re-save) | **~6:00–10:00 PM PT tonight** (02:00–06:00Z Nov 20) | Requires **per-slot** tried clear + **fresh timestamped GO** on **≥3** historical slots without `same_tok_retry` loop; rolling **28→13→30** one at a time + verify `pdeep_test_list n>0` for **≥15 min** before next |
| **Sustained historical complete_ppm ≥ 5** on top of refresh | **~10:00 PM–2:00 AM PT** (06:00–10:00Z) | Need **≥8** slots past token-poison loop; may need **overlay/supervisor** patch so failed run clears tried and does not relaunch on identical GO |
| **~1,500 need-list completes** | **~4–6 days** from first sustained historical throughput | Unchanged order of magnitude; Population queue ready |

## What fleet-cursor is doing (Shreyas: always fix, never park)

- Continue **single-slot** pilot care + **unique GO** (no mass restart).
- Next code fix (same branch): supervisor / recover **clear `pdeep_tried` + block `same_tok_retry` without new GO**.
- Will flip this doc again when **first historical `win_complete`** appears in `fleet_measure.json`.

Refresh / votes-per-snapshot: unchanged on **9/27/38**.