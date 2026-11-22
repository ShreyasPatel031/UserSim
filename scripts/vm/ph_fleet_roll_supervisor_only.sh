#!/usr/bin/env bash
# Push supervisor_strat.sh to /opt/ph/overlays on all non-upvote/non-live fleet VMs and restart phsuper.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
VM_GCS="${PACE_GCS_VM_ROOT:?}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:?}"
UPVOTE_SLOTS="${FLEET_UPVOTE_SLOTS:-9 27 38}"
LIVE_SLOTS="${FLEET_LIVE_SLOTS:-39}"
"${GC[@]}" storage cp "$ROOT/scripts/vm/reuse_overlays/supervisor_strat.sh" "${VM_GCS}/_code/overlays/supervisor_strat.sh"
REMOTE='set -e
B=$(grep -E "^PACE_GCS_VM_ROOT=" /opt/ph/pace.env | cut -d= -f2-)
TMP=/tmp/ph-overlay-roll
rm -rf "$TMP" && mkdir -p "$TMP"
gcloud storage cp -q "$B/_code/overlays/*.py" "$B/_code/overlays/supervisor_strat.sh" "$TMP/" 2>/dev/null || true
[[ -s "$TMP/supervisor_strat.sh" ]] && sudo install -m755 "$TMP/supervisor_strat.sh" /opt/ph/overlays/supervisor_strat.sh
sudo cp -f "$TMP"/*.py /opt/ph/overlays/ 2>/dev/null || true
sudo systemctl stop phsuper 2>/dev/null || true
sudo pkill -TERM -f "[p]deep.py|[p]h_batch.py" 2>/dev/null || true
sleep 2
EA=""; [[ -f /opt/ph/pace.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/pace.env"; [[ -f /opt/ph/strategy.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/strategy.env"
sudo systemd-run --unit=phsuper --collect -p WorkingDirectory=/opt/ph/reuse $EA \
  /bin/bash -c "bash /opt/ph/overlays/supervisor_strat.sh >> /opt/ph/reuse/supervisor.log 2>&1"
echo ROLL_SUP_OK'
while read -r slot _; do
  [[ -z "$slot" || "$slot" == \#* ]] && continue
  [[ " ${UPVOTE_SLOTS} " == *" $slot "* ]] && continue
  [[ " ${LIVE_SLOTS} " == *" $slot "* ]] && continue
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || continue
  (
    r="$("${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet --ssh-flag=-oConnectTimeout=20 \
      </dev/null --command="$REMOTE" 2>/dev/null | tail -1 || true)"
    echo "slot=$slot ${r:-SSH_FAIL}"
  ) &
  while (( $(jobs -rp | wc -l) >= 6 )); do sleep 1; done
done <"$ART/slots.tsv"
wait
echo ROLL_SUPERVISOR_DONE