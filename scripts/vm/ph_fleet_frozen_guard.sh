#!/usr/bin/env bash
# Honor results/ph_fleet_full/<run>/fleet_frozen_slots.txt — no create/recreate/wakeup on these slots while paused.
# Source after FLEET_ART or PACE_FLEET_RUN_ID is set.
fleet_frozen_slots_file() {
  local art="${FLEET_ART:-}"
  if [[ -z "$art" && -n "${PACE_FLEET_RUN_ID:-}" ]]; then
    local root="${PACE_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
    art="$root/results/ph_fleet_full/${PACE_FLEET_RUN_ID,,}"
  fi
  echo "${FLEET_FROZEN_SLOTS_FILE:-$art/fleet_frozen_slots.txt}"
}

fleet_slot_is_frozen() {
  local slot="${1:-}"
  [[ -n "$slot" ]] || return 1
  local f; f="$(fleet_frozen_slots_file)"
  [[ -f "$f" ]] || return 1
  awk -v s="$slot" 'NF && $1 !~ /^#/ && $1+0==$1 && $1==s {found=1} END{exit !found}' "$f"
}

fleet_frozen_guard_or_skip() {
  local slot="$1" what="$2"
  if fleet_slot_is_frozen "$slot"; then
    echo "frozen_slot_skip slot=$slot action=$what"
    return 0
  fi
  return 1
}