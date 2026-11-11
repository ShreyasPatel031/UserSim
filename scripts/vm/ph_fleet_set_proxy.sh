#!/usr/bin/env bash
# Point all running fleet VMs at PACE_PROXY_FILE and upload ISP/fixed-port overlays + strategy.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
[[ -f "${PACE_PROXY_FILE:-}" ]] || { echo "Set PACE_PROXY_FILE (e.g. secrets/iproyal.purl)" >&2; exit 1; }
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt")}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
STRATEGY="${PH_FLEET_STRATEGY_ENV:-$ROOT/scripts/vm/ph_strategies/fleet_iproyal.env}"
PROXY_FILE="${PACE_PROXY_FILE}"

echo "proxy-url from $PROXY_FILE strategy=$STRATEGY run=$RUN_ID"
while IFS=$'\t' read -r slot _; do
  [[ -z "$slot" || "$slot" == \#* ]] && continue
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$PACE_ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || continue
  "${GC[@]}" compute instances add-metadata "$name" --zone="$PACE_ZONE" \
    --metadata-from-file="proxy-url=$PROXY_FILE,ph-strategy-env=$STRATEGY" >/dev/null
  echo "metadata OK $name"
done <"$ART/slots.tsv"

SKIP_UPLOAD=0 STRATEGY="$STRATEGY" PROXY_ROLL=1 bash "$ROOT/scripts/vm/ph_fleet_roll_patches.sh"
