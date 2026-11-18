# Orchestrator 16:34Z reply

## (1) Missing 06:30 PT launch-day snapshot — one line

**Box:** `posts_ts` stall/pause after **0615PT** (watchdog alert **15:29Z**, slot file not processed until **0638PT**), so no timely `snapshots/20261118T0630PT_api.jsonl` from the box at slot time. **Slot 39:** at **14:30Z** (06:30 PT) `ph_fleet_live_capture.sh` ran `api_snap.py` for `20261118T0630` and logged **`api_snap failed`** (no object on GCS); fleet had already written **0600+0615** at prior slot opens—shared **6,250/15m** API budget + co-primary at `FLEET_CAPTURE_STANDBY_SEC=0`, not 3m-overdue standby.

## (2) Prior asks (one line each — unchanged; see `2026-11-18T15:34Z_orchestrator_three_one_liners.md`)

- **`-rN` GO:** `ph_fleet_full_experiment.sh` keeper (`nudge_go`→`write_go`); disabled `FLEET_KEEPER_NUDGE_GO=0`, loop restarted **12:35Z**.
- **`1vXYi…`:** `bsit_full15.tgz` older than full18f; fleet stays **full18f** + `PH_REQUIRE_FULL_SAVE` / `patch_require_full_save` / `pdeep.whole()`.
- **HOLD cleared:** **19** historical VMs on full18f pdeep; no autoscale scale-up this agent; no scale-up during live critical-stale.

**Status ~16:32Z:** 5 active / 7 dead / 6 stale / 1 cf_wall, **~1.13 cppm**.