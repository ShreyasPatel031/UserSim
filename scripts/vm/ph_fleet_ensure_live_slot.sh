#!/usr/bin/env bash
# Create slot FLEET_LIVE_SLOTS (default 39) and run ph_fleet_live_capture as primary (no pdeep).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
SLOT="${FLEET_LIVE_SLOTS:-39}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:?}"
PROJECT="${GCP_PROJECT:?}"
BUCKET="${MVP_GCS_BUCKET:?}"
MACHINE="${PH_FLEET_MACHINE:-e2-standard-2}"
STRATEGY_ENV="${PH_FLEET_STRATEGY:-$ROOT/scripts/vm/ph_strategies/fleet_optimize.env}"
PORT_PREFIX="${PACE_PORT_REGISTRY_PREFIX:-gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm/_ports}"
VM_GCS="${PACE_GCS_VM_ROOT:-gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"
TEMPLATE="${PACE_TEMPLATE:-}"
COMMON_META="pkg-name=full18f_candidate.tgz;pkg-md5=uYYdW17hoPBJjpMGoR7lKw==;k-levels=1,1;pace-state=0 600 0"
export PACE_REPO_ROOT="$ROOT" PACE_FLEET_RUN_ID="$RUN_ID" FLEET_ART="$ART"

vm_name() { echo "feeder-fleet-${RUN_ID}-${1}"; }

proxy_for_slot() {
  export PACE_REPO_ROOT="$ROOT" PACE_FLEET_RUN_ID="$RUN_ID" FLEET_ART="$ART"
  python3 "$ROOT/scripts/vm/ph_iproyal_assignments.py" get "$1" 2>/dev/null || echo "${PACE_PROXY_FILE:-$ROOT/.purl}"
}

next_port() {
  local taken p
  taken="$("${GC[@]}" storage ls "${PORT_PREFIX}/" 2>/dev/null | sed -n 's/.*port\.\([0-9]*\).*/\1/p' | sort -nu)"
  for p in $(seq 10000 20000); do
    echo "$taken" | grep -qx "$p" && continue
    awk -F'\t' '{print $2}' "$ART/slots.tsv" 2>/dev/null | grep -qx "$p" && continue
    echo "$p"; return 0
  done
  return 1
}

create_live_vm() {
  local port=$1 proxy_file name meta
  name="$(vm_name "$SLOT")"
  proxy_file="$(proxy_for_slot "$SLOT")"
  [[ -f "$proxy_file" ]] || proxy_file="${PACE_PROXY_FILE:-$ROOT/.purl}"
  meta="^;^proxy-port=${port};${COMMON_META};fleet-slot=${SLOT};fleet-live=1"
  echo "==> create $name port=$port"
  "${GC[@]}" compute instances create "$name" \
    --project="$PROJECT" --zone="$ZONE" \
    --machine-type="$MACHINE" \
    --network=main-vpc --subnet=primary-subnet \
    --image-family=pace-feeder --image-project="$PROJECT" --boot-disk-size=20GB \
    --service-account="$SA" --scopes=cloud-platform \
    --tags=allow-iap-ssh \
    --metadata-from-file "proxy-url=$proxy_file,ph-strategy-env=$STRATEGY_ENV,pace-boot-env=$ART/pace.env,startup-script=$ROOT/pace_startup.sh" \
    --metadata "$meta"
  printf '%s fleet-%s\n' "$name" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" | "${GC[@]}" storage cp - "${PORT_PREFIX}/port.${port}"
}

if ! awk -F'\t' -v s="$SLOT" '$1==s{found=1} END{exit !found}' "$ART/slots.tsv" 2>/dev/null; then
  port="$(next_port)"
  echo -e "${SLOT}\t${port}" >>"$ART/slots.tsv"
  python3 "$ROOT/scripts/vm/ph_iproyal_assignments.py" rebalance 2>&1 | tail -1 || true
  create_live_vm "$port"
fi

name="feeder-fleet-${RUN_ID}-${SLOT}"
for _ in $(seq 1 36); do
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] && break
  sleep 10
done
[[ "$st" == RUNNING ]] || { echo "slot $SLOT VM not RUNNING ($st)"; exit 1; }

"${GC[@]}" storage cp "$ROOT/scripts/vm/ph_fleet_live_capture.sh" \
  "${VM_GCS}/_code/ph_fleet_live_capture.sh" >/dev/null
echo "live:fleet-${RUN_ID}-capture" | "${GC[@]}" storage cp - "${VM_GCS}/GO.${name}"

LIVE_REMOTE='set -e
sudo systemctl stop phsuper 2>/dev/null || true
sudo pkill -TERM -f "[p]deep.py|[p]h_batch.py|[c]amoufox" 2>/dev/null || true
mkdir -p /opt/ph/live
B=$(grep PACE_GCS_VM_ROOT /opt/ph/pace.env | cut -d= -f2-)
sudo mkdir -p /opt/ph/live
sudo gcloud storage cp -q "$B/_code/ph_fleet_live_capture.sh" /opt/ph/live/ph_fleet_live_capture.sh
sudo chmod +x /opt/ph/live/ph_fleet_live_capture.sh
sudo systemctl stop phlive 2>/dev/null || true
EA=""; [[ -f /opt/ph/pace.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/pace.env"
sudo systemd-run --unit=phlive --collect -p WorkingDirectory=/opt/ph/live $EA \
  /bin/bash -c "exec /opt/ph/live/ph_fleet_live_capture.sh >>/var/log/phlive.log 2>&1" >/dev/null
sleep 3; pgrep -af ph_fleet_live_capture | head -2; echo LIVE_SLOT_OK'

"${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet --ssh-flag=-oConnectTimeout=25 \
  </dev/null --command="$LIVE_REMOTE" 2>&1 | tail -8
echo "live slot $SLOT ready"