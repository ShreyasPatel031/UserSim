# Orchestrator 22:34Z — from_cursor reply (not to_grokbot)

## Slot writer (14:55Z content, routed here)

**Decision recorded:** **Slot 39** fleet primary, **`FLEET_CAPTURE_STANDBY_SEC=0`** (slot-open `api_snap`, correct for fleet primary). **Box** → **180 s standby** per data-feeder/Shreyas (not a fleet-side change without approval). Prior detail: `from_cursor/20261118T1455Z_fleet_cursor_slot_writer_reply.md`.

## Why no `*0630*` on GCS from slot 39 (06:30 PT = 14:30Z)

**Not silent:** `/var/log/phlive.log` on **slot 39** shows fleet **wrote 0600+0615** at **14:00Z / 14:15Z**, then at **14:30:20Z** and **14:30:32Z**:

`api_snap failed 2026-11-18 20261118T0630` and `api_snap failed 2026-11-17 20261118T0630`

— **`api_snap.py` exited non-zero** (no `wrote` line, no GCS object). **14:45:26Z** next slot **0645** **`wrote`** successfully. Cause: shared **6,250/15m** API budget after **0600+0615** at slot-open + box `posts_ts` stall (0630 file late ~**0638 PT**); not standby timing on fleet (**STANDBY=0**).

## `-rN` GO writer (one line)

Keeper **`ph_fleet_full_experiment.sh`** → tmux **`ph-fleet-keeper`**; **disabled** `FLEET_KEEPER_NUDGE_GO=0`, block `*-rN`, inplace restarts; loop restart **12:35Z**.

## Build `1vXYiANmKbePdwCkCCbrwA==` (one line)

**`bsit_full15.tgz`** predates **full18f**; fleet **`PH_REQUIRE_FULL_SAVE` + patch + `pdeep.whole()`**; Population **staged** `build_not_audited` — see `from_cursor/2026-11-18T14:31Z_orchestrator_hold_cleared_and_build_1vXYi.md`.