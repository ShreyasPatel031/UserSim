#!/usr/bin/env bash
# Pull pdeep_list.<vm>.txt + have_complete.txt from GCS onto each pdeep VM (refill uploads only to GCS).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:?}"
UPVOTE_SLOTS="${FLEET_UPVOTE_SLOTS:-9 27 38}"
LIVE_SLOTS="${FLEET_LIVE_SLOTS:-39}"
REMOTE='set -e
B=$(grep -E "^PACE_GCS_VM_ROOT=" /opt/ph/pace.env | cut -d= -f2-)
VM=$(hostname)
cd /opt/ph/reuse
gcloud storage cp -q "$B/pdeep_list.${VM}.txt" . 2>/dev/null || gsutil -q cp "$B/pdeep_list.${VM}.txt" . || { echo SYNC_LIST_MISSING; exit 1; }
LIVE="${B%/vm}"
gcloud storage cp -q "$LIVE/have_complete.txt" . 2>/dev/null || true
wc -l "pdeep_list.${VM}.txt" | awk "{print \"synced n=\"\$1}"'
set +e
n=0
while read -r slot _; do
  [[ -z "$slot" || "$slot" == \#* ]] && continue
  [[ " ${UPVOTE_SLOTS} " == *" $slot "* ]] && continue
  [[ " ${LIVE_SLOTS} " == *" $slot "* ]] && continue
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || continue
  out="$("${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet --ssh-flag=-oConnectTimeout=20 \
    </dev/null --command="$REMOTE" 2>/dev/null | tail -1)"
  echo "slot=$slot ${out:-SYNC_FAIL}"
  n=$((n + 1))
done <"$ART/slots.tsv"
echo "SYNC_PDEEP_LISTS done vm_count=$n"