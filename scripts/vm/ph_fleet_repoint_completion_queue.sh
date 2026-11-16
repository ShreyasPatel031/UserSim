#!/usr/bin/env bash
# Point pdeep slots at filtered completion queue (build fix_*, seed pdeep_list, roll strategy).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PACE_ENV_FILE="${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export PACE_FLEET_RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
# shellcheck source=/dev/null
source "$PACE_ENV_FILE"
export GCP_PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
export PACE_ZONE="${PACE_ZONE:-$(gcloud compute instances list --filter=\"name=feeder-fleet-${PACE_FLEET_RUN_ID,,}-30\" --format=\"value(zone.basename())\" 2>/dev/null)}"
RUN_ID="${PACE_FLEET_RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
QUEUE="${1:-usersim_sim/raw/_cursor/completion_queue_20261116T1049Z.txt}"
TAG="${2:-$(date -u +%Y%m%dT%H%MZ)}"
chmod +x "$ROOT/scripts/vm/ph_fleet_build_completion_fix_list.sh" "$ROOT/scripts/vm/ph_fleet_seed_completion_queue.sh"
BUILD_OUT="$(bash "$ROOT/scripts/vm/ph_fleet_build_completion_fix_list.sh" "$QUEUE" "$TAG")"
FIX_BASENAME="$(echo "$BUILD_OUT" | sed -n 's/^FIX_BASENAME=//p')"
[[ -n "$FIX_BASENAME" ]] || FIX_BASENAME="fix_completion_queue_${TAG}.txt"
# Pin strategy env for roll (uploaded with overlays).
STRAT="$ROOT/scripts/vm/ph_strategies/fleet_optimize.env"
if grep -q '^PH_RR_FILES=' "$STRAT"; then
  sed -i "s|^PH_RR_FILES=.*|PH_RR_FILES=${FIX_BASENAME}|" "$STRAT"
else
  echo "PH_RR_FILES=${FIX_BASENAME}" >>"$STRAT"
fi
export FLEET_COMPLETION_QUEUE="$QUEUE"
export FLEET_HOLD_UNHANG=1
echo "=== seed pdeep_list queue=$QUEUE (have_index filtered)"
PACE_FLEET_RUN_ID="$RUN_ID" bash "$ROOT/scripts/vm/ph_fleet_seed_completion_queue.sh" "$QUEUE"
echo "=== roll PH_RR_FILES=$FIX_BASENAME PH_FLEET_RR_ONLY=1"
export PH_FLEET_STRATEGY_ENV="$STRAT"
bash "$ROOT/scripts/vm/ph_fleet_roll_patches.sh"
echo "{\"utc\":\"$(date -u +%FT%TZ)\",\"queue\":\"$QUEUE\",\"fix\":\"$FIX_BASENAME\"}" >"$ART/completion_queue_active.json"
cat "$ART/completion_queue_active.json"