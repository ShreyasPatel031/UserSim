#!/usr/bin/env bash
# Weekly close: board_ts homepage section "Last week" at 23:45 PT (route-4 / boxbrowser).
# Requires Camoufox on the host (Data Feeder or dedicated capture VM).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
DAY="${1:-$(TZ=America/Los_Angeles date +%F)}"
TAG="$(TZ=America/Los_Angeles date +%Y%m%dT%H%M)PT"
B="gs://${MVP_GCS_BUCKET}/usersim_sim/raw/ph_at_launch"
TOOLS="$B/live/tools/boxbrowser"
TMP=/tmp/ph_weekly_close_$$
mkdir -p "$TMP"
gcloud storage cp -q "$TOOLS/bb_capture.py" "$TOOLS/bb_load.py" "$TMP/" 2>/dev/null || true
if ! python3 -c "from camoufox.sync_api import Camoufox" 2>/dev/null; then
  echo "WEEKLY_CLOSE_SKIP no_camoufox on host; need Data Feeder or route-4 VM (official page read, not API)" >&2
  exit 2
fi
python3 "$TMP/bb_capture.py" --day "$DAY" --gap 15 --max-posts 0 2>&1 | tee "$TMP/run.log"
echo "weekly_close tag=$TAG day=$DAY done"