#!/usr/bin/env bash
# Pool B slots run usersim-poolb.service only — stop PH phsuper/pdeep so IPs stay for signed-in pulls.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:?}"
POOL_B="${FLEET_POOL_B_PINNED_SLOTS:-32 40 42 44 45}"
REMOTE='sudo systemctl stop phsuper 2>/dev/null || true
sudo pkill -TERM -f "[p]deep.py|[p]h_batch.py" 2>/dev/null || true
sudo pkill -TERM -f "[c]amoufox" 2>/dev/null || true
echo POOLB_PHSUPER_STOPPED'

for slot in $POOL_B; do
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || { echo "skip slot=$slot status=$st"; continue; }
  r="$("${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet --ssh-flag=-oConnectTimeout=20 \
    </dev/null --command="$REMOTE" 2>/dev/null | tail -1 || echo SSH_FAIL)"
  echo "poolb_stop slot=$slot $r"
done