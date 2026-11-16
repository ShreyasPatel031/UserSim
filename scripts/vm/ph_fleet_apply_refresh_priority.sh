#!/usr/bin/env bash
# Wait for E5 refresh_priority_<day>.txt, merge ahead of activity queue, reseed + roll upvote slots 9/27/38.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export GCP_PROJECT PACE_ZONE MVP_GCS_BUCKET PACE_FLEET_RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${PACE_FLEET_RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
PRIORITY_DAYS="${REFRESH_PRIORITY_DAYS:-2026-11-13 2026-11-14 2026-11-15}"
WAIT_POLL_SEC="${WAIT_POLL_SEC:-30}"
WAIT_MAX_SEC="${WAIT_MAX_SEC:-7200}"
TAIL_GCS="${REFRESH_TAIL_GCS:-usersim_sim/raw/_cursor/refresh_upvotes_20261116T0145Z_fleet.txt}"
UPVOTE_SLOTS="${UPVOTE_SLOTS:-9 27 38}"

echo "=== wait refresh_priority days: $PRIORITY_DAYS (max ${WAIT_MAX_SEC}s)"
deadline=$((SECONDS + WAIT_MAX_SEC))
for day in $PRIORITY_DAYS; do
  obj="usersim_sim/raw/_cursor/refresh_priority_${day}.txt"
  while ! gcloud storage ls "gs://${MVP_GCS_BUCKET}/${obj}" &>/dev/null; do
    if (( SECONDS > deadline )); then
      echo "TIMEOUT waiting $obj" >&2
      exit 1
    fi
    echo "waiting gs://${MVP_GCS_BUCKET}/${obj} ..."
    sleep "$WAIT_POLL_SEC"
  done
  echo "ready $obj"
done

TAG="$(date -u +%Y%m%dT%H%MZ)"
export REFRESH_PRIORITY_DAYS="$PRIORITY_DAYS" REFRESH_TAIL_GCS="$TAIL_GCS"
META="$(bash "$ROOT/scripts/vm/ph_fleet_merge_upvote_refresh_queue.sh" "$TAG")"
MERGED_BASENAME="refresh_upvotes_${TAG}_priority_merged.txt"
MERGED_GCS="usersim_sim/raw/_cursor/${MERGED_BASENAME}"
echo "$META" | tee "$ART/upvote_priority_merge_${TAG}.json"

FIRST_DAY="${PRIORITY_DAYS%% *}"
FIRST_OBJ="usersim_sim/raw/_cursor/refresh_priority_${FIRST_DAY}.txt"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
gcloud storage cp "gs://${MVP_GCS_BUCKET}/${FIRST_OBJ}" "$TMP/first.txt"
FIRST_N="$(python3 -c "print(sum(1 for ln in open('$TMP/first.txt') if ln.strip() and not ln.lstrip().startswith('#')))")"

DEPLOYED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 <<PY
import json
from pathlib import Path
state = {
    "deployed_utc": "$DEPLOYED_UTC",
    "first_priority_day": "$FIRST_DAY",
    "first_priority_gcs": "gs://${MVP_GCS_BUCKET}/${FIRST_OBJ}",
    "first_priority_n": $FIRST_N,
    "merged_gcs": "gs://${MVP_GCS_BUCKET}/${MERGED_GCS}",
    "merged_basename": "$MERGED_BASENAME",
    "priority_days": "$PRIORITY_DAYS".split(),
    "upvote_slots": "$UPVOTE_SLOTS".split(),
    "orchestrator_done_relayed": False,
}
Path("$ART/upvote_refresh_priority.state.json").write_text(json.dumps(state, indent=2))
print(json.dumps(state, indent=2))
PY

export PACE_ENV_FILE="$ROOT/results/ph_fleet_full/${RUN_ID}/pace.env"
export PRESERVE_QUEUE_CACHE=0
bash "$ROOT/scripts/vm/ph_fleet_seed_upvote_refresh.sh" "$MERGED_GCS"
export ONLY_SLOTS="$UPVOTE_SLOTS"
export PH_FLEET_STRATEGY_ENV="$ROOT/scripts/vm/ph_strategies/fleet_optimize.env"
export PH_UPVOTE_STRATEGY_ENV="$ROOT/scripts/vm/ph_strategies/fleet_upvote_refresh.env"
bash "$ROOT/scripts/vm/ph_fleet_roll_patches.sh"

echo "UPVOTE_PRIORITY_APPLIED deployed_utc=$DEPLOYED_UTC merged=$MERGED_GCS first_day=$FIRST_DAY n=$FIRST_N"