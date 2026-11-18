#!/usr/bin/env bash
# One fleet-fix timer tick: measure, proxies, recover, mailbox status (orchestrator contract).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PACE_ENV_FILE="${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export PACE_FLEET_RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
# shellcheck source=/dev/null
source "$PACE_ENV_FILE"
unset PACE_SERVICE_ACCOUNT
# Hung slots recover one at a time (cooldown + per-tick cap in recover), never as a fleet-wide restart.
export FLEET_HOLD_UNHANG="${FLEET_HOLD_UNHANG:-0}"
export FLEET_STALE_UNHANG_MIN_COMPLETE_PPM="${FLEET_STALE_UNHANG_MIN_COMPLETE_PPM:-0}"
export FLEET_STALE_UNHANG_MAX="${FLEET_STALE_UNHANG_MAX:-3}"
export FLEET_WAKEUP_MAX="${FLEET_WAKEUP_MAX:-12}"
export FLEET_REFILL_JOB_SPLIT="${FLEET_REFILL_JOB_SPLIT:-1}"
export FLEET_REFILL_SKIP_COMPLETE_QUEUED="${FLEET_REFILL_SKIP_COMPLETE_QUEUED:-1}"
export FLEET_STALE_UNHANG_WRITE_GO="${FLEET_STALE_UNHANG_WRITE_GO:-0}"
python3 "$ROOT/scripts/vm/ph_fleet_measure.py"
python3 "$ROOT/scripts/vm/ph_fleet_refill_lists.py" || true
bash "$ROOT/scripts/vm/ph_iproyal_ensure_slot_proxies.sh" >/dev/null 2>&1 || true
bash "$ROOT/scripts/vm/ph_fleet_utilization_recover.sh"
chmod +x "$ROOT/scripts/vm/ph_fleet_cursor_mailbox_status.sh" 2>/dev/null || true
bash "$ROOT/scripts/vm/ph_fleet_cursor_mailbox_status.sh"