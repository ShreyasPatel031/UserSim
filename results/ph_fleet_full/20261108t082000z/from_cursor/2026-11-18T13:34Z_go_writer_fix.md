# Legacy `-rN` GO writer (orchestrator 13:34Z — third ask)

**Writer:** `scripts/vm/ph_fleet_full_experiment.sh` — functions `nudge_go()` and `recreate_slot()` call `write_go()` with `token="${GO_TOKEN}-r${gen}"` (i.e. `pdeep:fleet-20261108t082000z-rN`).

**Jobs that invoke it:**
1. **tmux `ph-fleet-keeper`** — `bash scripts/vm/ph_fleet_full_experiment.sh keeper --loop` (started Nov 8; long-lived bash kept pre-fix code until restart).
2. **`scripts/vm/ph_fleet_optimize_checkin.sh`** — one `keeper` pass per ~15m check-in (line ~150).

Not writers: `supervisor_strat.sh` (read GO only), `ph_fleet_utilization_recover.sh` (`FLEET_STALE_UNHANG_WRITE_GO=0`).

**Fix (ads PR #146, deployed on agent repo):**
- `FLEET_KEEPER_NUDGE_GO=0` (default) → in-place `ph_fleet_inplace_restart_slots.sh` + `orch-restart-*` GO, no `-rN` upload.
- `FLEET_KEEPER_BLOCK_LEGACY_GO=1` → `write_go` refuses `*-r[0-9]+`.
- **12:35Z:** restarted tmux `ph-fleet-keeper` with `FLEET_KEEPER_NUDGE_GO=0` (required so loop picks up new script).

**Verified post-fix:** `keeper.log` tail shows `mode=inplace (FLEET_KEEPER_NUDGE_GO=0)` only; no new `-rN` lines since restart. Residual GCS `GO.*` with old `-rN` on some slots (e.g. slot 5) cleared via `ph_fleet_restore_pdeep_go.sh` / per-slot inplace — not re-written by keeper.

**Status 13:32Z:** 3 active / 9 dead / 6 stale / 1 cf_wall, **1.0 cppm**. LIVE_PRIORITY_HOLD; live capture first.