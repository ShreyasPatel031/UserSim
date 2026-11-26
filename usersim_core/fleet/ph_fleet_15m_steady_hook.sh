#!/usr/bin/env bash
# Turnkey 15-minute telemetry & steady-backoff hook for fleet-cursor (`ph_fleet_fix_tick.sh`).
# Safe & non-destructive:
#   - Never stops, pauses, or deletes any GCE VM (`AGENTS.md` L152).
#   - Uploads fresh `iproyal_rotate.log` and `iproyal_assignments.json` to `mailbox/from_cursor/` every 15m tick
#     (resolving the stale Nov 20 dashboard snapshot gap identified with `fleet-cursor`).
#   - Computes `/tmp/steady_slot_actions.json` via `usersim_core.fleet.steady_ip_pool` so `cf_wall` slots enter
#     proper exponential cooldown + 0.5x worker step-down instead of restarting `phsuper` in a tight loop on a burned IP.

set -euo pipefail

BUCKET="${MVP_GCS_BUCKET:-usersim-bakeoff-347838016394}"
FLEET_RUN_DIR="${FLEET_RUN_DIR:-/agent/repos/usersim/results/ph_fleet_full/20261108t082000z}"
STATUS_JSON="${STATUS_JSON:-/tmp/cursor_status.json}"
STATE_JSON="${STATE_JSON:-/var/tmp/usersim_steady_ip_state.json}"
OUT_PLAN="${OUT_PLAN:-/tmp/steady_slot_actions.json}"

# 1. Publish fresh IPRoyal assignments & live rotate ledger to mailbox/from_cursor/ every 15m tick
if [[ -f "${FLEET_RUN_DIR}/iproyal_assignments.json" ]]; then
  gcloud storage cp -q "${FLEET_RUN_DIR}/iproyal_assignments.json" \
    "gs://${BUCKET}/usersim_sim/mailbox/from_cursor/iproyal_assignments.json" || true
fi

if [[ -f "${FLEET_RUN_DIR}/iproyal_rotate.log" ]]; then
  gcloud storage cp -q "${FLEET_RUN_DIR}/iproyal_rotate.log" \
    "gs://${BUCKET}/usersim_sim/mailbox/from_cursor/iproyal_rotate.log.full" || true
fi

# 2. Evaluate non-ping-ponging exponential backoff & dead-supervisor recovery actions
if [[ -f "${STATUS_JSON}" ]]; then
  python3 -m usersim_core.fleet.steady_ip_pool tick \
    --status-json "${STATUS_JSON}" \
    --assignments-json "${FLEET_RUN_DIR}/iproyal_assignments.json" \
    --state-json "${STATE_JSON}" \
    --out-plan "${OUT_PLAN}"

  gcloud storage cp -q "${OUT_PLAN}" \
    "gs://${BUCKET}/usersim_sim/mailbox/from_cursor/steady_slot_actions_latest.json" || true
fi
