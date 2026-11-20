#!/usr/bin/env bash
# Post-close month-wide official API read for the launch day that just ended (MTD day-end).
# Writes monthly_reread/<YYYY-MM>/<launch-day>_official_reread.jsonl with votesCount + monthlyRank.
# Run after 00:00 PT for that day (target delivery ~02:00 PT).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export MVP_GCS_BUCKET PH_AT_LAUNCH_GCS_ROOT="gs://${MVP_GCS_BUCKET}/usersim_sim"
CLOSE_DAY="${1:-$(TZ=America/Los_Angeles date -d 'yesterday' +%F 2>/dev/null || TZ=America/Los_Angeles date -v-1d +%F)}"
export PH_MONTHLY_REREAD_MODE=live
exec python3 "$ROOT/runtime/phlaunch/monthly_reread.py" --read-date "$CLOSE_DAY" --post-close