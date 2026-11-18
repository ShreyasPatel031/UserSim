#!/usr/bin/env bash
# Split fleet_work_queue by job: refresh_priority -> upvote slots; incomplete+new -> pdeep (06:34Z orchestrator).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
export GCP_PROJECT MVP_GCS_BUCKET PACE_FLEET_RUN_ID="$RUN_ID"
export FLEET_REFILL_JOB_SPLIT=1 FLEET_REFILL_SKIP_COMPLETE_QUEUED=1 FLEET_STALE_UNHANG_WRITE_GO=0

QUEUE="$(gcloud storage ls "gs://${MVP_GCS_BUCKET}/usersim_sim/raw/_cursor/completion_queue_"*.txt 2>/dev/null | tail -1 || true)"
QUEUE="${QUEUE##gs://${MVP_GCS_BUCKET}/}"
[[ -n "$QUEUE" ]] || { echo "no completion_queue" >&2; exit 1; }
export FLEET_COMPLETION_QUEUE="$QUEUE"

REFRESH="${FLEET_REFRESH_PRIORITY_QUEUE:-usersim_sim/raw/_cursor/refresh_priority_latest.txt}"
echo "=== upvote seed refresh_priority=${REFRESH}"
bash "$ROOT/scripts/vm/ph_fleet_seed_upvote_refresh.sh" "$REFRESH"

echo "=== completion fix + PH_RR_FILES queue=${QUEUE}"
TAG="$(date -u +%Y%m%dT%H%MZ)"
FIX_META="$(bash "$ROOT/scripts/vm/ph_fleet_build_completion_fix_list.sh" "$QUEUE" "$TAG")"
FIX_BASENAME="fix_completion_queue_${TAG}.txt"
echo "$FIX_META"

echo "=== pdeep refill (job split)"
FORCE=1 FLEET_WORK_QUEUE="usersim_sim/raw/_cursor/fleet_work_queue.txt" \
  python3 "$ROOT/scripts/vm/ph_fleet_refill_lists.py" | tee "$ART/job_split_refill_${TAG}.json"

python3 <<PY
import json
from pathlib import Path
p = Path("$ART/completion_queue_active.json")
p.write_text(json.dumps({
  "utc": "$(date -u +%FT%TZ)",
  "queue": "$QUEUE",
  "fix_rr_file": "$FIX_BASENAME",
  "job_split": True,
  "refresh_priority": "$REFRESH",
}, indent=2))
PY

export ONLY_SLOTS="${UPVOTE_SLOTS:-9 27 38}"
export PH_UPVOTE_STRATEGY_ENV="$ROOT/scripts/vm/ph_strategies/fleet_upvote_refresh.env"
bash "$ROOT/scripts/vm/ph_fleet_roll_patches.sh" || true

echo "JOB_SPLIT_APPLIED queue=$QUEUE refresh=$REFRESH fix=$FIX_BASENAME"