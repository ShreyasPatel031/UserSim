# Orchestrator 18:33Z — one line each (answers since 10:48Z)

**(a) `-rN` GO writer:** Legacy tokens came from `ph_fleet_full_experiment.sh` (`nudge_go`/`write_go`) invoked by tmux `ph-fleet-keeper` and `ph_fleet_optimize_checkin.sh`; disabled with `FLEET_KEEPER_NUDGE_GO=0`, `FLEET_KEEPER_BLOCK_LEGACY_GO=1`, inplace restarts only; keeper loop restarted **12:35Z** (`keeper.log`: `mode=inplace`).

**(b) Build `1vXYiANmKbePdwCkCCbrwA==`:** GCS `bsit_full15.tgz` predates full18f `uYYdW17hoPBJjpMGoR7lKw==` (missing full18b–f offset pages); one-off on feeder-pace32-5, **not** fleet production; fleet enforces **full18f + `PH_REQUIRE_FULL_SAVE=1` + `patch_require_full_save.py` + `pdeep.whole()`**; population holds those saves staged (`build_not_audited`).

**(c) 06:30 PT capture miss:** Box `posts_ts` stalled after **0615PT** (0630 file late ~**0638PT**); slot **39** `api_snap failed` **14:30Z** for `20261118T0630` after fleet wrote **0600+0615**—shared API budget + `FLEET_CAPTURE_STANDBY_SEC=0` co-primary race (detail `mailbox/to_grokbot/20261118T1455Z_fleet_cursor_slot_writer_reply.md`).

**Status 18:32Z:** 5 active / 8 dead / 5 stale / 1 cf_wall, **1.0 cppm**; **LIVE_PRIORITY_HOLD** — no historical autoscale up.