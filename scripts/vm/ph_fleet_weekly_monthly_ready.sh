#!/usr/bin/env bash
# Write weekly/monthly close readiness to ART + optional GCS (orchestrator 10:45Z review).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
PRIMARY="${PH_WEEKLY_CLOSE_SLOT:-9}"
FALLBACK="${PH_WEEKLY_CLOSE_FALLBACK_SLOT:-27}"
SLOT="$PRIMARY"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
NAME="feeder-fleet-${RUN_ID}-${SLOT}"
local_camoufox=0
python3 -c "from camoufox.sync_api import Camoufox" 2>/dev/null && local_camoufox=1 || true
fleet_camoufox=0
st="$("${GC[@]}" compute instances describe "$NAME" --zone="${PACE_ZONE:?}" --format='value(status)' 2>/dev/null || echo MISSING)"
if [[ "$st" == RUNNING ]]; then
  fleet_camoufox=$("${GC[@]}" compute ssh "$NAME" --zone="${PACE_ZONE}" --tunnel-through-iap --quiet \
    --ssh-flag=-oConnectTimeout=12 </dev/null --command='/opt/venv/bin/python -c "from camoufox.sync_api import Camoufox"' 2>/dev/null && echo 1 || echo 0)
fi
monthly_token=0
[[ -n "${PH_API_TOKEN:-}" || -n "${PH_API_DEV_TOKEN:-}" ]] && monthly_token=1
TAG="$(date -u +%FT%TZ)"
python3 <<PY >"$ART/weekly_monthly_ready.json"
import json
print(json.dumps({
  "utc": "$TAG",
  "weekly_close": {
    "next": "2026-11-22T23:45:00-08:00",
    "cron_pt": "2345",
    "path": "ph_weekly_close_fleet.sh",
    "slot": $SLOT,
    "slot_fallback": $FALLBACK,
    "vm_status": "$st",
    "agent_camoufox": bool($local_camoufox),
    "fleet_camoufox_slot": bool($fleet_camoufox),
  },
  "monthly_reread": {
    "next": "2026-11-30T23:50:00-08:00",
    "cron_pt": "2350",
    "path": "ph_monthly_reread.sh",
    "agent_api_token_set": bool($monthly_token),
    "mode_default": "${PH_MONTHLY_REREAD_MODE:-live}",
  },
}, indent=2))
PY
cat "$ART/weekly_monthly_ready.json"
if [[ -n "${MVP_GCS_BUCKET:-}" ]]; then
  gcloud storage cp "$ART/weekly_monthly_ready.json" \
    "gs://${MVP_GCS_BUCKET}/usersim_sim/mailbox/from_cursor/weekly_monthly_ready.json" 2>/dev/null || true
fi