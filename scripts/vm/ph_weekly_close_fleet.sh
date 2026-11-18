#!/usr/bin/env bash
# Weekly close (route-4 "Last week") on a fleet VM with Camoufox — not on the cloud-agent image.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
SLOT="${PH_WEEKLY_CLOSE_SLOT:-26}"
DAY="${1:-$(TZ=America/Los_Angeles date +%F)}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
NAME="feeder-fleet-${RUN_ID}-${SLOT}"
BUCKET="${MVP_GCS_BUCKET:?}"
TOOLS="gs://${BUCKET}/usersim_sim/raw/ph_at_launch/live/tools/boxbrowser"
CMD=$(cat <<EOS
set -e
TMP=/tmp/ph_weekly_close_\$\$
mkdir -p "\$TMP"
gcloud storage cp -q "${TOOLS}/bb_capture.py" "${TOOLS}/bb_load.py" "\$TMP/"
/opt/venv/bin/python -c "from camoufox.sync_api import Camoufox"
/opt/venv/bin/python "\$TMP/bb_capture.py" --day "${DAY}" --gap 15 --max-posts 0
echo weekly_close_fleet_vm ok day=${DAY}
EOS
)
"${GC[@]}" compute ssh "$NAME" --zone="${PACE_ZONE:?}" --tunnel-through-iap --quiet \
  --ssh-flag=-oConnectTimeout=30 </dev/null --command="$CMD"
echo "weekly_close fleet slot=$SLOT day=$DAY"