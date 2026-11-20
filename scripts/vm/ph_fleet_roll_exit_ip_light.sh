#!/usr/bin/env bash
# Install exit_ip audit overlays without full phsuper restart storm.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export GCP_PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
export PACE_ZONE="${PACE_ZONE:-$(gcloud compute instances list --project="$GCP_PROJECT" --filter="name~feeder-fleet-${RUN_ID}" --format='value(zone)' 2>/dev/null | head -1)}"
ZONE="$PACE_ZONE"
D="$ROOT/scripts/vm/reuse_overlays"
VM_GCS="${PACE_VM_GCS:-gs://${MVP_GCS_BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"
OVERLAY_GCS="${VM_GCS}/_code/overlays"
GC=(gcloud --account="$SA")
if [[ "${SKIP_UPLOAD:-0}" != 1 ]]; then
  "${GC[@]}" storage cp "$D/exit_ip_util.py" "$D/exit_ip_heartbeat.sh" "$D/patch_exit_ip_audit.py" "$D/supervisor_strat.sh" "${OVERLAY_GCS}/" 2>/dev/null || true
fi
REMOTE='set -u
B=$(grep -E "^PACE_GCS_VM_ROOT=" /opt/ph/pace.env | cut -d= -f2-)
O=/opt/ph/overlays
mkdir -p "$O"
gcloud storage cp -q "$B/_code/overlays/exit_ip_util.py" "$B/_code/overlays/exit_ip_heartbeat.sh" "$B/_code/overlays/patch_exit_ip_audit.py" "$B/_code/overlays/supervisor_strat.sh" "$O/" 2>/dev/null || true
chmod +x "$O/exit_ip_heartbeat.sh" 2>/dev/null || true
[[ -x /opt/venv/bin/python && -f "$O/patch_exit_ip_audit.py" ]] && sudo /opt/venv/bin/python "$O/patch_exit_ip_audit.py" /opt/ph/reuse 2>>/opt/ph/reuse/supervisor.log || true
pgrep -f "[e]xit_ip_heartbeat.sh" >/dev/null || sudo setsid bash "$O/exit_ip_heartbeat.sh" >>/opt/ph/reuse/supervisor.log 2>&1 &
export VM="$(hostname)"
[[ -f /opt/ph/pace.env ]] && export PACE_GCS_VM_ROOT="$(grep -E '^PACE_GCS_VM_ROOT=' /opt/ph/pace.env | cut -d= -f2-)"
[[ -x /opt/venv/bin/python && -f "$O/exit_ip_util.py" ]] && sudo -E /opt/venv/bin/python "$O/exit_ip_util.py" log exit_ip_resume "light_roll" 2>>/opt/ph/reuse/supervisor.log || true
echo EXIT_IP_LIGHT_OK'
set +e
while IFS=$'\t' read -r slot _; do
  [[ -z "$slot" || "$slot" == \#* ]] && continue
  name="feeder-fleet-${RUN_ID}-${slot}"
  st=$(gcloud --account="$SA" compute instances describe "$name" --zone="$ZONE" --project="$GCP_PROJECT" --format='value(status)' 2>/dev/null || echo MISSING)
  [[ "$st" == RUNNING ]] || { echo "slot=$slot SKIP_${st}"; continue; }
  out=$(gcloud --account="$SA" compute ssh "$name" --zone="$ZONE" --project="$GCP_PROJECT" --tunnel-through-iap --quiet \
    --ssh-flag=-oConnectTimeout=20 </dev/null --command="$REMOTE" 2>/dev/null | tail -1)
  echo "slot=$slot ${out:-SSH_FAIL}"
done <"$ROOT/results/ph_fleet_full/${RUN_ID}/slots.tsv"
set -e