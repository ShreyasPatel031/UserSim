#!/usr/bin/env bash
# Stop (not delete) fleet VMs when throughput is zero — billing hold per orchestrator deadline.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:?}"
MIN_PPM="${1:-1}"
python3 "$ROOT/scripts/vm/ph_fleet_measure.py"
ppm="$(python3 -c "import json; print(json.load(open('$ART/fleet_measure.json')).get('complete_ppm',0))")"
if python3 -c "exit(0 if float('$ppm') < float('$MIN_PPM') else 1)" 2>/dev/null; then
  echo "STOP_IDLE complete_ppm=$ppm < $MIN_PPM — stopping RUNNING fleet VMs"
  while IFS=$'\t' read -r slot _; do
    [[ -z "$slot" || "$slot" == \#* ]] && continue
    name="feeder-fleet-${RUN_ID}-${slot}"
    st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
    [[ "$st" == RUNNING ]] || continue
    echo "stop $name"
    "${GC[@]}" compute instances stop "$name" --zone="$ZONE" --quiet </dev/null 2>/dev/null || true
  done <"$ART/slots.tsv"
  echo "STOP_IDLE done"
else
  echo "STOP_IDLE skip complete_ppm=$ppm >= $MIN_PPM"
fi