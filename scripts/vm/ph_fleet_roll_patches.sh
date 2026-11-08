#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
export GCP_PROJECT PACE_ZONE MVP_GCS_BUCKET
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt")}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
VM_GCS="${PACE_VM_GCS:-gs://${MVP_GCS_BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"
OVERLAY_GCS="${VM_GCS}/_code/overlays"
STRATEGY="$ROOT/scripts/vm/ph_strategies/fleet_optimize.env"
D="$ROOT/scripts/vm/reuse_overlays"

"${GC[@]}" storage cp \
  "$D"/*.py "$D/supervisor_strat.sh" "$D/ensure_geoip.sh" \
  "${OVERLAY_GCS}/"
"${GC[@]}" storage cp "$STRATEGY" "${OVERLAY_GCS}/fleet_optimize.env"

REMOTE_CMD='set -e
B=$(grep -E "^PACE_GCS_VM_ROOT=" /opt/ph/pace.env | cut -d= -f2-)
TMP=/tmp/ph-overlay-roll
rm -rf "$TMP" && mkdir -p "$TMP"
gcloud storage cp -q \
  "$B/_code/overlays/patch_week_bytes.py" \
  "$B/_code/overlays/patch_stop_first_block.py" \
  "$B/_code/overlays/patch_dynamic_paged.py" \
  "$B/_code/overlays/patch_soft_block_rotate.py" \
  "$B/_code/overlays/patch_soft_open_rotate.py" \
  "$B/_code/overlays/patch_same_port_retry.py" \
  "$B/_code/overlays/patch_lazy_tabs.py" \
  "$B/_code/overlays/patch_require_full_save.py" \
  "$B/_code/overlays/fleet_optimize.env" \
  "$TMP/" 2>/dev/null || true
sudo cp -f "$TMP"/*.py /opt/ph/overlays/ 2>/dev/null || true
sudo cp -f "$TMP/fleet_optimize.env" /opt/ph/strategy.env 2>/dev/null || true
export PH_BLOCK_ROTATE_SLEEP_SEC=15 PH_BLOCK_SAME_PORT_RETRIES=2 PH_BLOCK_SAME_PORT_SLEEP_SEC=20
for p in patch_week_bytes.py patch_stop_first_block.py patch_dynamic_paged.py patch_soft_block_rotate.py patch_soft_open_rotate.py patch_same_port_retry.py patch_lazy_tabs.py patch_require_full_save.py; do
  [[ -f /opt/ph/overlays/$p ]] && sudo /opt/venv/bin/python /opt/ph/overlays/$p 2>&1 | sudo tee -a /var/log/phreuse_start.log >/dev/null || true
done
if pgrep -f ph_batch.py >/dev/null 2>&1; then
  pkill -f ph_batch.py || true
  sleep 2
fi
echo ROLL_OK'

while IFS=$'\t' read -r slot _port; do
  [[ -z "$slot" || "$slot" == \#* ]] && continue
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$PACE_ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || continue
  echo "==> roll $name"
  "${GC[@]}" compute instances add-metadata "$name" --zone="$PACE_ZONE" \
    --metadata-from-file="ph-strategy-env=$STRATEGY" >/dev/null 2>&1 || true
  "${GC[@]}" compute ssh "$name" --zone="$PACE_ZONE" --tunnel-through-iap --quiet \
    </dev/null --command="$REMOTE_CMD" 2>/dev/null | tail -1 || true
done <"$ART/slots.tsv"
