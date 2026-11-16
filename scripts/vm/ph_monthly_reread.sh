#!/usr/bin/env bash
# Official API monthly re-read -> raw/ph_at_launch/monthly_reread/<YYYY-MM>/<read_date>.jsonl
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export MVP_GCS_BUCKET PH_AT_LAUNCH_GCS_ROOT="gs://${MVP_GCS_BUCKET}/usersim_sim"
READ_DATE="${1:-$(TZ=America/Los_Angeles date +%F)}"
MODE="${PH_MONTHLY_REREAD_MODE:-backfill}"  # backfill | live
OPTS=(--read-date "$READ_DATE")
if [[ "$MODE" == backfill ]]; then
  OPTS+=(--backfill-from-snapshots)
fi
exec python3 "$ROOT/runtime/phlaunch/monthly_reread.py" "${OPTS[@]}"