#!/usr/bin/env bash
# Schedule hooks (run from cron on fleet babysit / cloud agent with PT timezone).
# 23:45 PT — weekly close homepage read (route-4; not API-only).
# 23:50 PT — monthly official-API re-read.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export MVP_GCS_BUCKET
H=$(TZ=America/Los_Angeles date +%H%M)
case "$H" in
  2345)
    echo "$(date -u +%FT%TZ) weekly_close: invoke route-4 homepage Last week (see ph_weekly_close.sh)"
    exec bash "$ROOT/scripts/vm/ph_weekly_close.sh" || true
    ;;
  2350)
    export PH_MONTHLY_REREAD_MODE="${PH_MONTHLY_REREAD_MODE:-live}"
    exec bash "$ROOT/scripts/vm/ph_monthly_reread.sh"
    ;;
  *)
    echo "usage: cron at 2345 or 2350 PT only (now PT H%M=$H)" >&2
    exit 0
    ;;
esac