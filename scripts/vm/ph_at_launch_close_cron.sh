#!/usr/bin/env bash
# Schedule hooks (run from cron on fleet babysit / cloud agent with PT timezone).
# 23:45 PT — weekly close homepage read (route-4; not API-only).
# 23:50 PT — monthly official-API pre-close rollup (orchestrator: not day-end).
# 01:45 PT — post-close month-wide read for yesterday’s launch day (day-end / MTD).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export MVP_GCS_BUCKET
H=$(TZ=America/Los_Angeles date +%H%M)
case "$H" in
  2345)
  echo "$(date -u +%FT%TZ) weekly_close: route-4 via fleet VM (ph_weekly_close_fleet.sh; local ph_weekly_close.sh if Camoufox present)"
  if python3 -c "from camoufox.sync_api import Camoufox" 2>/dev/null; then
    exec bash "$ROOT/scripts/vm/ph_weekly_close.sh" || true
  else
    exec bash "$ROOT/scripts/vm/ph_weekly_close_fleet.sh" || true
  fi
    ;;
  2350)
    export PH_MONTHLY_REREAD_MODE="${PH_MONTHLY_REREAD_MODE:-live}"
    exec bash "$ROOT/scripts/vm/ph_monthly_reread.sh"
    ;;
  0145)
    exec bash "$ROOT/scripts/vm/ph_post_close_month_reread.sh"
    ;;
  *)
    echo "usage: cron at 2345, 2350, or 0145 PT only (now PT H%M=$H)" >&2
    exit 0
    ;;
esac