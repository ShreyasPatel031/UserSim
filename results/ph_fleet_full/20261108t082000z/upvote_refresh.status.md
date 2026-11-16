# upvote_refresh.status (fleet-cursor)

**Run:** `20261108t082000z`  
**Updated (UTC):** `2026-11-16T18:12Z`  
**LIVE_PRIORITY_HOLD:** no historical fleet scale-up  

## Root cause (08:50Z orchestrator / Population audit)

Slots **9, 27, 38** were labeled upvote_refresh but **`GO.*` was overwritten to `pdeep:fleet-…` by fleet-wide patch rolls** — workers ran full **pdeep**, not **`repullupvotes`**.  
When `repullupvotes` runs via `ph_batch.py`, saves historically went to **`people_live/vm/{handle}.json`**, not Population staging **`raw/_pacetest/shared`**, so audits saw **0 refresh deltas**.

## Fix deployed (08:51–08:54Z)

1. **`patch_ph_batch_save_sb.py`** — uploads `out/{handle}.json` → **`PH_SAVE_B`** = `gs://…/usersim_sim/raw/_pacetest/shared/{handle}.json` (same as pdeep).
2. **`patch_repull_upvotes_staging.py`** — load base person from **SB**; on success set:
   - **`upvotes_refreshed_at`** (UTC string, `now()`)
   - **`upvotes.refresh`**: `{read_utc, delta: {items_before, items_after, items_added}}`
   - **`run.upvotes_repulled`**, **`run.finished_utc`** (Population may also use **`run.finished_utc`**)
3. **`ph_fleet_roll_patches.sh`** — slots **9/27/38** keep **`repullupvotes:…`** GO + **`fleet_upvote_refresh.env`** on full-fleet rolls (`upvote_go.token`).
4. Restarted: **`repullupvotes:fleet-upvote-20261108t082000z-20261116T0851Z`**, queue **`raw/_cursor/refresh_upvotes_20261116T0145Z_fleet.txt`** (82,661 handles).

## Where refresh output lands (contract)

| Item | Value |
|------|--------|
| **GCS path** | `gs://{bucket}/usersim_sim/raw/_pacetest/shared/{handle}.json` |
| **Format** | Whole-person JSON (existing complete record merged) |
| **Upvotes** | `upvotes.items[]` replaced/merged; paging in `upvotes.paging` |
| **Refresh stamp** | Top-level **`upvotes_refreshed_at`**; nested **`upvotes.refresh.read_utc`** + **`upvotes.refresh.delta.*`** |
| **Run time** | **`run.finished_utc`** on upload |
| **Logs** | `{vm}/logs/{handle}.log` under `people_live/vm` |
| **Status** | `{vm}/status/{vm}.jsonl` events with `mode=repullupvotes` |

## Progress (09:19Z)

| Metric | Value |
|--------|--------|
| **GO clobber RCA** | Keeper `nudge_go` wrote `pdeep:fleet-…-rN` to slots **9/27/38** again (~09:14Z). Fixed: keeper skips upvote slots; autoscale uses `upvote_go.token`; recover already skipped. |
| **Relaunch** | `repullupvotes:fleet-upvote-20261108t082000z-20261116T0918Z` on 9/27/38 (ROLL_OK) |
| People refreshed (staging uploads w/ stamp) | pending (first SB merges after relaunch) |
| Pages read (mean / p95) | pending |
| New upvotes appended | pending |
| Dedicated slots | **9, 27, 38** — **ph_batch `--mode repullupvotes`** confirmed running |

## Progress (11:09Z) — write gate RCA

| Metric | Value |
|--------|--------|
| RCA | `ph_batch.py` full7 gate allowed only `--mode pdeep`; `repullupvotes` exited rc=5 instantly (`only pdeep PDEEP_MODE=full may write`) |
| Fix | `patch_repallow_upvotes_write.py` + supervisor overlay sync; rolled **9/27/38** (`ROLL_OK`) |
| Verify | Slot **9** running `ph_batch.py --mode repullupvotes` after roll |

## Progress (10:59Z)

| Metric | Value |
|--------|--------|
| Fleet measure | `complete_ppm=1.87`, `active_vms=8` (gates not met; `stale_unhang` paused) |
| Upvote slot state | **9/38** `dead` (win_complete=0); **27** `dead` but win_complete=1 in 15m window |
| Action | `ph_fleet_inplace_restart_slots.sh 9 27 38` → **INPLACE_RESTART_STARTING** (GO=`upvote_go.token`) |

## References

- `scripts/vm/ph_fleet_start_upvote_refresh.sh`, `fleet_upvote_refresh.env`
- `results/ph_fleet_full/20261108t082000z/upvote_go.token`