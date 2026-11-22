#!/usr/bin/env bash
# One fleet-fix timer tick: measure, proxies, recover, mailbox status (orchestrator contract).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PACE_ENV_FILE="${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export PACE_FLEET_RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
# shellcheck source=/dev/null
source "$PACE_ENV_FILE"
if [[ -z "${PACE_ZONE:-}" ]]; then
  export PACE_ZONE="$(gcloud compute instances list --filter="name~'^feeder-fleet-${PACE_FLEET_RUN_ID}-' AND status=RUNNING" --format='value(zone)' 2>/dev/null | head -1)"
fi
POSTURE="${PACE_ENV_FILE%.env}/fleet_posture.env"
[[ -f "$POSTURE" ]] && source "$POSTURE"
export FLEET_KEEPER_DISABLED="${FLEET_KEEPER_DISABLED:-0}"
export FLEET_HISTORICAL_PULL_PAUSE="${FLEET_HISTORICAL_PULL_PAUSE:-0}"
export FLEET_HOLD_UNHANG="${FLEET_HOLD_UNHANG:-0}"
export FLEET_WAKEUP_MAX="${FLEET_WAKEUP_MAX:-12}"
unset PACE_SERVICE_ACCOUNT
# Hung slots recover one at a time (cooldown + per-tick cap in recover), never as a fleet-wide restart.
export FLEET_HOLD_UNHANG="${FLEET_HOLD_UNHANG:-0}"
export FLEET_STALE_UNHANG_MIN_COMPLETE_PPM="${FLEET_STALE_UNHANG_MIN_COMPLETE_PPM:-0}"
export FLEET_STALE_UNHANG_MAX="${FLEET_STALE_UNHANG_MAX:-3}"
export FLEET_WAKEUP_MAX="${FLEET_WAKEUP_MAX:-12}"
export FLEET_REFILL_JOB_SPLIT="${FLEET_REFILL_JOB_SPLIT:-1}"
export FLEET_REFILL_SKIP_COMPLETE_QUEUED="${FLEET_REFILL_SKIP_COMPLETE_QUEUED:-1}"
export FLEET_STALE_UNHANG_WRITE_GO="${FLEET_STALE_UNHANG_WRITE_GO:-1}"
python3 "$ROOT/scripts/vm/ph_fleet_measure.py"
ART="$ROOT/results/ph_fleet_full/${PACE_FLEET_RUN_ID,,}"
if [[ "${FLEET_HISTORICAL_PULL_PAUSE:-0}" == 1 && -x "$ROOT/scripts/vm/ph_fleet_pilot28_care.sh" ]]; then
  _p28="$(python3 - "$ART/fleet_measure.json" <<'PY' 2>/dev/null || echo skip
import json, sys
m = json.load(open(sys.argv[1]))
for s in m.get("slots") or []:
    if s.get("slot") != 28:
        continue
    st = s.get("state") or ""
    age = s.get("age") or 0
    if st == "dead":
        print("care")
    elif st == "stale" and age > 1800 and (s.get("ppm_complete") or 0) < 0.05:
        print("care")
    break
else:
    print("skip")
PY
)"
  if [[ "$_p28" == care ]]; then
    bash "$ROOT/scripts/vm/ph_fleet_pilot28_care.sh" || true
    python3 "$ROOT/scripts/vm/ph_fleet_measure.py"
  fi
fi
python3 "$ROOT/scripts/vm/ph_fleet_refill_lists.py" || true
python3 "$ROOT/scripts/vm/ph_fleet_stacks_pull_hour.py" >/dev/null 2>&1 || true
python3 "$ROOT/scripts/vm/ph_fleet_refresh_end_reasons.py" >/dev/null 2>&1 || true
python3 "$ROOT/scripts/vm/ph_fleet_tab_failure_counts.py" >/dev/null 2>&1 || true
bash "$ROOT/scripts/vm/ph_iproyal_ensure_slot_proxies.sh" >/dev/null 2>&1 || true
bash "$ROOT/scripts/vm/ph_fleet_utilization_recover.sh"
chmod +x "$ROOT/scripts/vm/ph_fleet_cursor_mailbox_status.sh" 2>/dev/null || true
bash "$ROOT/scripts/vm/ph_fleet_cursor_mailbox_status.sh"