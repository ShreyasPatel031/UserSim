#!/usr/bin/env bash
# Rotate a fleet slot to the next Finland dedicated IP (pool), rebind metadata, wipe geo, restart phsuper.
#   ./scripts/vm/ph_iproyal_rotate_slot.sh 7 block
#   ./scripts/vm/ph_iproyal_rotate_slot.sh 7 recreate
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PACE_REPO_ROOT="$ROOT"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt" 2>/dev/null)}"
RUN_ID="${RUN_ID,,}"
export PACE_FLEET_RUN_ID="$RUN_ID" FLEET_ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
SLOT="${1:?slot}"
REASON="${2:-block}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:-$("${GC[@]}" compute instances list --project="$GCP_PROJECT" --filter='name~feeder-fleet' --limit=1 --format='value(zone)')}"

res="$(python3 "$ROOT/scripts/vm/ph_iproyal_assignments.py" rotate "$SLOT" "$REASON")"
echo "$res"
echo "$res" | python3 -c "import json,sys; sys.exit(0 if json.load(sys.stdin).get('ok') else 1)" || exit 0

purl="$(python3 "$ROOT/scripts/vm/ph_iproyal_assignments.py" get "$SLOT")"
[[ -f "$purl" ]] || exit 1
name="feeder-fleet-${RUN_ID}-${SLOT}"
st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
[[ "$st" == RUNNING ]] || { echo "skip $name status=$st"; exit 0; }

STRAT="${PH_FLEET_STRATEGY_ENV:-$ROOT/results/ph_iproyal_limit/strategy_L3_mid.env}"
[[ -f "$STRAT" ]] || STRAT="$ROOT/results/ph_iproyal_limit/strategy_L3_mid.env"
"${GC[@]}" compute instances add-metadata "$name" --zone="$ZONE" \
  --metadata-from-file="proxy-url=$purl,ph-strategy-env=$STRAT" >/dev/null
echo "iproyal_rotate slot=$SLOT bound $(python3 -c "import urllib.parse as u; print(u.urlparse(open('$purl').read().strip()).hostname)") reason=$REASON"

"${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet </dev/null \
  --command='sudo rm -f /opt/ph/reuse/cf_cooldown_until /opt/ph/reuse/cf_backoff_n /opt/ph/reuse/same_tok_retry_at /opt/ph/reuse/iproyal_rotate_request 2>/dev/null
sudo rm -rf /opt/ph/profiles/* /opt/ph/reuse/.strat_cleaned 2>/dev/null; sudo mkdir -p /opt/ph/profiles
if [[ -x /opt/ph/overlays/proxy_geo_sync.sh ]]; then
  B=$(grep -E "^PACE_GCS_VM_ROOT=" /opt/ph/pace.env | cut -d= -f2-)
  PACE_GCS_VM_ROOT="$B" bash /opt/ph/overlays/proxy_geo_sync.sh >>/opt/ph/reuse/supervisor.log 2>&1 || true
fi
FORCE_GEOIP_REFRESH=1 PACE_GCS_VM_ROOT="'"$(grep PACE_GCS_VM_ROOT "$ROOT/results/ph_fleet_full/${RUN_ID}/pace.env" 2>/dev/null | cut -d= -f2- || echo "gs://${MVP_GCS_BUCKET}/usersim_sim/raw/ph_population/people_live/vm")"'" sudo -E bash /opt/ph/overlays/ensure_geoip.sh 2>/dev/null || true
sudo systemctl restart phsuper' 2>/dev/null || echo "ssh rotate follow-up skipped $name"
LOG="$ROOT/results/ph_fleet_full/${RUN_ID}/iproyal_rotate.log"
echo "$(date -u +%FT%TZ) $res" >>"$LOG"
