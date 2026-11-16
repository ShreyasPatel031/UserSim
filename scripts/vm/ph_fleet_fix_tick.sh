#!/usr/bin/env bash
# One fleet-fix timer tick: measure, proxies, recover, mailbox status (orchestrator contract).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PACE_ENV_FILE="${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export PACE_FLEET_RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
# shellcheck source=/dev/null
source "$PACE_ENV_FILE"
unset PACE_SERVICE_ACCOUNT
# Orchestrator crisis: no stale_unhang / wakeup loops while clean supervisor restart runs.
export FLEET_HOLD_UNHANG="${FLEET_HOLD_UNHANG:-1}"
export FLEET_WAKEUP_MAX="${FLEET_WAKEUP_MAX:-0}"
python3 "$ROOT/scripts/vm/ph_fleet_measure.py"
bash "$ROOT/scripts/vm/ph_iproyal_ensure_slot_proxies.sh" >/dev/null 2>&1 || true
bash "$ROOT/scripts/vm/ph_fleet_utilization_recover.sh"
chmod +x "$ROOT/scripts/vm/ph_fleet_cursor_mailbox_status.sh" 2>/dev/null || true
bash "$ROOT/scripts/vm/ph_fleet_cursor_mailbox_status.sh"