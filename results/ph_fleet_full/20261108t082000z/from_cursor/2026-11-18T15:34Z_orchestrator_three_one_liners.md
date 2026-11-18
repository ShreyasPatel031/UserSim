# Orchestrator 15:34Z — three one-liners (reply to 14:31Z)

**(a) Legacy `-rN` GO writer:** `ph_fleet_full_experiment.sh` (`nudge_go`→`write_go`) via tmux `ph-fleet-keeper --loop` + `ph_fleet_optimize_checkin.sh` keeper; **fix** `FLEET_KEEPER_NUDGE_GO=0`, block `*-rN` in `write_go`, keeper loop restarted **12:35Z** (`mode=inplace` in `keeper.log` since).

**(b) Build `1vXYiANmKbePdwCkCCbrwA==`:** GCS `bsit_full15.tgz` (**older than** full18f `uYYdW…` — drops full18b–f offset re-page in `paging_v2.py`/`ph_batch.py`/`pdeep.whole`); one staged save on `feeder-pace32-5`, **not** fleet deploy; fleet full-only = **full18f + `PH_REQUIRE_FULL_SAVE=1` + `patch_require_full_save.py` + `pdeep.whole()`** (detail: `from_cursor/2026-11-18T14:31Z_orchestrator_hold_cleared_and_build_1vXYi.md`).

**(c) HOLD cleared (14:31Z):** Historical slots **19 RUNNING** on full18f pulling pdeep (`ph_fleet_fix_tick` / utilization recover); **no autoscale scale-up** applied this turn — brief live-stale windows still treated as no scale-up; orchestrator clearance = use all historical slots for throughput when feeds ok (slot **39** live capture, not pdeep).

**Status ~15:32Z:** 3 active / ~11 dead / ~5 stale, **~1.0 cppm**, ~17h partial fleet outage; queue **5000**.