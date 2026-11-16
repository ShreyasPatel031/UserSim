# upvote_refresh.status (fleet-cursor)

**Run:** `20261108t082000z`  
**Updated (UTC):** `2026-11-16T23:42Z`  
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

## refresh_priority (orchestrator 18:10Z)

E5 writes `usersim_sim/raw/_cursor/refresh_priority_<YYYY-MM-DD>.txt` (~2.3k predicted voters/day). Fleet drains **priority days first** (after 00:00 PT close), then activity tail `refresh_upvotes_*_fleet.txt`.

| Step | Script |
|------|--------|
| Merge + wait | `ph_fleet_apply_refresh_priority.sh` |
| Watch + done relay | `ph_fleet_refresh_priority_watch.sh` (tmux) |
| Progress | `ph_fleet_refresh_priority_progress.py` |

**Now (18:34Z):** merged `refresh_upvotes_20261116T1834Z_priority_merged.txt` (days **13→16** oldest-first + activity tail); rolled **9/27/38**. ACK orchestrator `22625546419676885`; DONE relay when **2026-11-13** drained (`upvote_refresh_priority.state.json`, tmux watch).

## Progress (22:40Z) — orchestrator restart + priority reapply

| Metric | Value |
|--------|--------|
| RCA (stale thrash) | `FLEET_HOLD_UNHANG=1` had set `FLEET_WAKEUP_MAX=0` → **zero** dead/cf wakeups; fixed (hold still blocks stale_unhang only) |
| Stale restart | `ph_fleet_inplace_restart_slots.sh` **9 27 38 40 34 31 29 30** (existing IPs) |
| Priority queue | `refresh_upvotes_20261116T2235Z_priority_merged.txt` (**82,700** handles; day **13** first **2,256**); seeded + ROLL_OK **9/27/38** |
| Workers | `ph_batch --mode repullupvotes` live on **9/27/38** since **22:37Z** |
| Stamped SB uploads | **0** so far post-restart (ramp ~36s/tab); watch `_pacetest/shared` + `done_n` in priority progress |
| Fleet post-fix | **22:38Z** measure: complete_ppm **1.93**, active **6**, stale **9** (recovering) |

## Progress (23:42Z) — orchestrator 23:35Z + upvote RCA

| Metric | Value |
|--------|--------|
| Clean restart | **23:36–23:39Z** priority `2336Z`, pdeep seed+roll (non-upvote), inplace **11** slots |
| Upvote RCA | **Pre-start `for h in handles` gsutil backup** on ~**27k**/VM partition + full `gsutil ls B/*.json` before `start` event → workers stuck **hours** with 0-byte run logs (not prescreen). Fix: **`patch_repull_upvotes_lazy_bak.py`** (lazy per-person backup; skip vm-wide have scan) |
| Seed fix | `ph_fleet_seed_completion_queue.sh` now **skips slots 9/27/38** (ab4aa49c) |
| Post-restart | **~23:40Z** complete_ppm **0.8**, active **6**, stale **10**; refresh **0/2256** |
| Live feeds | **23:45 / 23:50 PT** weekly close + monthly re-read **preempt** fleet work (timer subs) |

## References

- `scripts/vm/ph_fleet_start_upvote_refresh.sh`, `fleet_upvote_refresh.env`
- `results/ph_fleet_full/20261108t082000z/upvote_go.token`