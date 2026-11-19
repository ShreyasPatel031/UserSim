#!/usr/bin/env bash
# Weekly close when route-4 browser read is blocked: official API weekly ranks (no evasion).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export MVP_GCS_BUCKET GCP_PROJECT GOOGLE_CLOUD_PROJECT="${GCP_PROJECT:-}"
export PH_AT_LAUNCH_GCS_ROOT="gs://${MVP_GCS_BUCKET}/usersim_sim"
DAY="${1:-$(TZ=America/Los_Angeles date +%F)}"
export PYTHONPATH="${ROOT}/runtime/phlaunch${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "$ROOT/runtime/phlaunch/weekly_close_api.py" --day "$DAY"