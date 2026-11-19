# Shreyas policy + fleet unpark (2026-11-19 ~12:28 PM PT)

**Operator rule (this chat only):** always fix in place on sticky IPRoyal bindings; never park/stop/freeze fleet for orchestrator ops. Orchestrator 20:25Z acknowledged 05:44Z/08:35Z stops were their error, not operator intent.

**Posture:** `fleet_posture.env` — `FLEET_HISTORICAL_PULL_PAUSE=0`, `FLEET_AUTOSCALE_FROZEN=0`, keeper on with `FLEET_KEEPER_NUDGE_GO=0`. `fleet_frozen_slots.txt` cleared.

**LIVE_PRIORITY_HOLD:** scale historical only when `ph_fleet_live_priority.sh` reports `critical_stale` (20:25Z: false; `api_comments` warning-only).

**Unpark:** `scripts/vm/ph_fleet_unpark_slots.sh` — `gcloud compute instances start` + GO + clear `pdeep_tried` + `PH_FLEET_BLOCK_PAUSE=0` + phsuper relaunch (no recreate).

**Population:** ACK REPAIR_LIST 20261119T2021Z — queue 4,905; COMPLETE 93,399.