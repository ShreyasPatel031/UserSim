#!/usr/bin/env bash
# In-place phsuper restart on existing sticky IP (no VM recreate, no proxy rotate).
# Usage: PACE_FLEET_RUN_ID=... ./ph_fleet_inplace_restart_slots.sh 30 31 ...
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
export FLEET_ART="$ART"
# shellcheck source=/dev/null
source "$ROOT/scripts/vm/ph_fleet_frozen_guard.sh"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:?}"
VM_GCS="${PACE_GCS_VM_ROOT:-gs://${MVP_GCS_BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"
UPVOTE_SLOTS="${FLEET_UPVOTE_SLOTS:-9 27 38}"
LIVE_SLOTS="${FLEET_LIVE_SLOTS:-39}"
UPVOTE_GO=""
[[ -f "$ART/upvote_go.token" ]] && UPVOTE_GO="$(tr -d '\n' <"$ART/upvote_go.token")"
[[ -z "$UPVOTE_GO" ]] && UPVOTE_GO="repullupvotes:fleet-upvote-${RUN_ID}"
TS="$(date +%s)"
REMOTE_STALE='set -e
sudo rm -f /opt/ph/reuse/cf_cooldown_until /opt/ph/reuse/cf_backoff_n /opt/ph/reuse/same_tok_retry_at /opt/ph/reuse/iproyal_rotate_request /opt/ph/reuse/last_token /opt/ph/reuse/KICK /opt/ph/reuse/port_override 2>/dev/null || true
sudo systemctl stop phsuper 2>/dev/null || true
sudo pkill -TERM -f "[p]deep.py|[p]h_batch.py" 2>/dev/null || true
sudo pkill -TERM -f "[c]amoufox" 2>/dev/null || true
sleep 2
EA=""; [[ -f /opt/ph/pace.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/pace.env"; [[ -f /opt/ph/strategy.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/strategy.env"
sudo systemd-run --unit=phsuper --collect -p WorkingDirectory=/opt/ph/reuse $EA /bin/bash -c "bash /opt/ph/overlays/supervisor_strat.sh >> /opt/ph/reuse/supervisor.log 2>&1" >/dev/null 2>&1
sleep 1
pgrep -f "[p]deep.py" >/dev/null && echo INPLACE_RESTART_OK || echo INPLACE_RESTART_STARTING
exit 0'
for slot in "$@"; do
  if fleet_slot_is_frozen "$slot"; then
    echo "skip slot=$slot frozen"
    continue
  fi
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || { echo "skip slot=$slot status=$st"; continue; }
  go="pdeep:fleet-${RUN_ID}-orch-restart-${TS}-${slot}"
  if [[ " ${UPVOTE_SLOTS} " == *" $slot "* ]]; then
    go="$UPVOTE_GO"
  elif [[ " ${LIVE_SLOTS} " == *" $slot "* ]]; then
    echo "skip slot=$slot live_primary"
    continue
  fi
  echo "$go" | "${GC[@]}" storage cp - "${VM_GCS}/GO.${name}" >/dev/null 2>&1 || true
  "${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet \
    --ssh-flag=-oConnectTimeout=15 </dev/null --command="$REMOTE_STALE" 2>/dev/null | tail -1 | sed "s/^/slot=$slot /" &
done
wait
echo "INPLACE_RESTART done slots=$*"