#!/usr/bin/env bash
# Recreate dedicated upvote-refresh VMs (slots 9, 27, 38) when GCE instances are missing.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export PACE_FLEET_RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${PACE_FLEET_RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
export FLEET_ART="$ART"
# shellcheck source=/dev/null
source "$ROOT/scripts/vm/ph_fleet_frozen_guard.sh"
UPVOTE_SLOTS="${FLEET_UPVOTE_SLOTS:-${UPVOTE_SLOTS:-9 27 38}}"
export PH_FLEET_STRATEGY="${PH_FLEET_STRATEGY:-$ROOT/scripts/vm/ph_strategies/fleet_upvote_refresh.env}"
# Re-use autoscale create_one (sticky port from slots.tsv, upvote GO token).
# shellcheck source=/dev/null
source "$ROOT/scripts/vm/ph_fleet_autoscale.sh"

for slot in $UPVOTE_SLOTS; do
  if fleet_slot_is_frozen "$slot"; then
    echo "skip frozen slot=$slot"
    continue
  fi
  name="$(vm_name "$slot")"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  if [[ "$st" == RUNNING ]]; then
    echo "ok slot=$slot RUNNING"
    continue
  fi
  port="$(awk -F'\t' -v s="$slot" '$1==s{print $2;exit}' "$ART/slots.tsv")"
  [[ -n "$port" ]] || { echo "no port in slots.tsv for slot=$slot" >&2; exit 1; }
  if [[ "$st" != MISSING && "$st" != "" ]]; then
  echo "slot=$slot status=$st (not creating; terminate/recreate manually if needed)"
  continue
  fi
  echo "==> create missing upvote slot=$slot port=$port"
  create_one "$slot" "$port"
done
echo ENSURE_UPVOTE_SLOTS_DONE