#!/usr/bin/env bash
# Pilot slot 28 only: clear pdeep_tried / stale claims so repull can page (historical pause; no VM recreate).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
SLOT="${FLEET_PILOT_SLOT:-28}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:?}"
VM_GCS="${PACE_GCS_VM_ROOT:?}"
BUCKET="${MVP_GCS_BUCKET:?}"
NAME="feeder-fleet-${RUN_ID}-${SLOT}"
GOOD="$NAME"
LIST="gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm/pdeep_list.${NAME}.txt"

python3 - "$BUCKET" "$RUN_ID" "$SLOT" "$GOOD" <<'PY'
import subprocess, sys
bkt, run, slot, good = sys.argv[1:5]
hs = subprocess.check_output(
    ["gcloud", "storage", "cat", f"gs://{bkt}/usersim_sim/raw/ph_population/people_live/vm/pdeep_list.feeder-fleet-{run}-{slot}.txt"],
    text=True,
).splitlines()
released = 0
for h in hs:
    h = h.strip()
    if not h:
        continue
    c = f"gs://{bkt}/usersim_sim/raw/ph_population/people_live/vm/claims/{h}"
    r = subprocess.run(["gcloud", "storage", "cat", c], capture_output=True, text=True)
    if r.returncode != 0:
        continue
    owner = r.stdout.strip()
    if owner and owner != good:
        subprocess.run(["gcloud", "storage", "rm", c], capture_output=True)
        released += 1
print(f"claims_released={released} handles={len([x for x in hs if x.strip()])}")
PY

echo "pdeep:fleet-${RUN_ID}" | "${GC[@]}" storage cp - "${VM_GCS}/GO.${NAME}"

REMOTE=$(cat <<'EOS'
set -e
B=$(grep PACE_GCS_VM_ROOT /opt/ph/pace.env | cut -d= -f2-)
VM=$(hostname)
sudo gcloud storage cp -q "$B/pdeep_list.${VM}.txt" /opt/ph/reuse/
sudo rm -f /opt/ph/reuse/pdeep_tried.json /opt/ph/reuse/last_token /opt/ph/reuse/same_tok_retry_at
sudo systemctl stop phsuper 2>/dev/null || true
sleep 1
EA=""; [[ -f /opt/ph/pace.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/pace.env"
[[ -f /opt/ph/strategy.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/strategy.env"
sudo systemd-run --unit=phsuper --collect -p WorkingDirectory=/opt/ph/reuse $EA \
  /bin/bash -c "bash /opt/ph/overlays/supervisor_strat.sh >> /opt/ph/reuse/supervisor.log 2>&1"
sleep 55
grep '"event": "pdeep_test_list"' /opt/ph/reuse/status_${VM}.jsonl 2>/dev/null | tail -1 || true
EOS
)
"${GC[@]}" compute ssh "$NAME" --zone="$ZONE" --tunnel-through-iap --quiet \
  --ssh-flag=-oConnectTimeout=20 </dev/null --command="$REMOTE"
echo "pilot28_care done slot=$SLOT"