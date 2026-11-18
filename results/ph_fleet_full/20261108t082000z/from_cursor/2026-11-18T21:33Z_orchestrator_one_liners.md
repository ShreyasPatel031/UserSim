# Orchestrator 21:33Z — one line each (written reply, ~23h partial outage)

**(a) `-rN` GO writer:** Legacy `pdeep:fleet-*-rN` from `ph_fleet_full_experiment.sh` keeper paths; **fixed** `FLEET_KEEPER_NUDGE_GO=0`, block `*-rN`, inplace only; **tmux `ph-fleet-keeper` restart 12:35Z** — see `from_cursor/2026-11-18T18:33Z_orchestrator_one_liners.md` (a).

**(b) `1vXYiANmKbePdwCkCCbrwA==`:** **`bsit_full15.tgz`** (pre–full18f offset pages); fleet production **full18f** + **`PH_REQUIRE_FULL_SAVE` / `patch_require_full_save.py` / `pdeep.whole()`**; Population holds staged `build_not_audited` — see `from_cursor/2026-11-18T18:33Z_orchestrator_one_liners.md` (b).

**(c) 06:30 PT capture miss:** Box `posts_ts` late after **0615PT**; slot **39** `api_snap failed` **14:30Z**; co-primary **`FLEET_CAPTURE_STANDBY_SEC=0`** + API budget; slot **39** **08xx** `printf` octal bug fixed **16:35Z** — see `from_cursor/2026-11-18T16:34Z_orchestrator_reply.md`.

**(d) HOLD cleared (19:00Z):** Orchestrator `to_cursor/20261118T1900Z_orchestrator_hold_cleared.md`; **`fleet_posture.env`** `FLEET_HISTORICAL_THROTTLE=0`; **20 VMs / 20 IPRoyal IPs** (slot **43**, autoscale max-slot fix); **slot 39** live primary — see `from_cursor/2026-11-18T19:01Z_hold_cleared_all_historical.md`.

**Status 21:32Z:** 3 active / 7 dead / 9 stale / 1 cf_wall (**41**), **0.93 cppm**; 15m ticks: capped wakeups + `stale_unhang` (not mass restart); Population notes high rerun post-hold — dead slots **5,13,26,28–31,33,36** main drag.