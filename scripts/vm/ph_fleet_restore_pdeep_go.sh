#!/usr/bin/env bash
# Restore pdeep GO on all non-upvote slots (fixes repullupvotes token leak via PH_GO_MODE).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export PACE_FLEET_RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${PACE_FLEET_RUN_ID,,}"
unset PACE_SERVICE_ACCOUNT
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
VM_GCS="${PACE_GCS_VM_ROOT:-gs://${MVP_GCS_BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"
UPVOTE_SLOTS="${FLEET_UPVOTE_SLOTS:-9 27 38}"
TS="$(date -u +%Y%m%dT%H%MZ)"
GO="pdeep:fleet-${RUN_ID}-restore-${TS}"
UPVOTE_GO=""
[[ -f "$ART/upvote_go.token" ]] && UPVOTE_GO="$(tr -d '\n' <"$ART/upvote_go.token")"
[[ -z "$UPVOTE_GO" ]] && UPVOTE_GO="repullupvotes:fleet-upvote-${RUN_ID}"
bash "$ROOT/scripts/vm/ph_fleet_inplace_restart_slots.sh" $(awk '{print $1}' "$ART/slots.tsv" | while read -r s; do
  [[ -z "$s" || "$s" == \#* ]] && continue
  [[ " $UPVOTE_SLOTS " == *" $s "* ]] && continue
  echo -n "$s "
done)