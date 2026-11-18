# Keeper legacy `GO.*` writer (orchestrator 11:34Z)

## Root cause

`pdeep:fleet-20261108t082000z-rN` tokens on GCS `GO.feeder-fleet-*` were **not** from `supervisor_strat.sh` (read-only) or `ph_fleet_utilization_recover.sh` (`FLEET_STALE_UNHANG_WRITE_GO=0` default).

**Writer:** `scripts/vm/ph_fleet_full_experiment.sh`

| Function | Behavior |
|----------|----------|
| `nudge_go()` | `token="${GO_TOKEN}-r${gen}"` then `write_go()` |
| `recreate_slot()` | same `-r${gen}` pattern on VM recreate |
| `write_go()` | `gcloud storage cp` → `gs://…/GO.${vm}` |

**Invoker (every ~15m):** `scripts/vm/ph_fleet_optimize_checkin.sh` line ~146:

`KEEPER_NUDGE_BUDGET=12 bash …/ph_fleet_full_experiment.sh keeper`

(`ph_fleet_fix_tick.sh` does not call keeper directly.)

## Fix (2026-11-18)

- Default **`FLEET_KEEPER_NUDGE_GO=0`**: `nudge_go` uses **`ph_fleet_inplace_restart_slots.sh`** (orch-restart GO), no legacy `-rN` upload.
- **`FLEET_KEEPER_BLOCK_LEGACY_GO=1`**: `write_go` refuses any token matching `*-r[0-9]+`.
- Recreate path uses `pdeep:fleet-{run}-keeper-recreate-{ts}-{slot}` when nudge-go experiment mode is off.
- Check-in skips keeper when **`PH_FLEET_LIVE_STALE_WARNING=1`** (live feed SLA).

Re-normalize historical GO: run `ph_fleet_restore_pdeep_go.sh` **after** the above is deployed (re-normalizing before keeper was disabled did not stick).

## Weekly close

`ph_weekly_close_fleet.sh`: primary slot **26**, fallback **30** when primary is `cf_wall`/dead or VM not `RUNNING`.

## Policy

**LIVE_PRIORITY_HOLD:** no historical fleet scale-up while live feeds are critical-stale; keeper also skipped on stale warning during check-in.