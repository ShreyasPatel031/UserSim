#!/usr/bin/env bash
# Start TERMINATED feeder VMs on existing bindings (no recreate), GO + in-place phsuper fix.
# Usage: ./ph_fleet_unpark_slots.sh [slot ...]   (default: all TERMINATED in slots.tsv)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
export FLEET_ART="$ART" PACE_FLEET_RUN_ID="$RUN_ID"
[[ -f "$ART/fleet_posture.env" ]] && source "$ART/fleet_posture.env"
# shellcheck source=/dev/null
source "$ROOT/scripts/vm/ph_fleet_frozen_guard.sh"
if [[ -x "$ROOT/scripts/vm/ph_fleet_live_priority.sh" ]]; then
  eval "$(bash "$ROOT/scripts/vm/ph_fleet_live_priority.sh" env 2>/dev/null)" || true
fi
if [[ "${PH_FLEET_LIVE_PRIORITY_HOLD:-0}" == 1 ]]; then
  echo "unpark_skip LIVE_PRIORITY_HOLD critical_stale feeds"
  exit 0
fi
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:?}"
VM_GCS="${PACE_GCS_VM_ROOT:?}"
STRATEGY="${PH_FLEET_STRATEGY:-$ROOT/scripts/vm/ph_strategies/fleet_iproyal.env}"
UPVOTE_SLOTS="${FLEET_UPVOTE_SLOTS:-9 27 38}"
LIVE_SLOTS="${FLEET_LIVE_SLOTS:-39}"
TS="$(date +%s)"
slots=()
if (($#)); then
  slots=("$@")
else
  mapfile -t slots < <(awk -F'\t' 'NF>=2 && $1+0==$1 {print $1}' "$ART/slots.tsv")
fi
REMOTE_BOOT='set -e
sudo rm -f /opt/ph/reuse/pdeep_tried.json /opt/ph/reuse/last_token /opt/ph/reuse/same_tok_retry_at \
  /opt/ph/reuse/cf_cooldown_until /opt/ph/reuse/cf_backoff_n 2>/dev/null || true
grep -q "^PH_FLEET_BLOCK_PAUSE=0" /opt/ph/strategy.env 2>/dev/null || \
  sudo sed -i "s/^PH_FLEET_BLOCK_PAUSE=.*/PH_FLEET_BLOCK_PAUSE=0/" /opt/ph/strategy.env 2>/dev/null || true
sudo systemctl stop phsuper 2>/dev/null || true
sudo pkill -TERM -f "[p]deep.py|[p]h_batch.py" 2>/dev/null || true
sleep 2
EA=""; [[ -f /opt/ph/pace.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/pace.env"
[[ -f /opt/ph/strategy.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/strategy.env"
sudo systemd-run --unit=phsuper --collect -p WorkingDirectory=/opt/ph/reuse $EA \
  /bin/bash -c "bash /opt/ph/overlays/supervisor_strat.sh >> /opt/ph/reuse/supervisor.log 2>&1"
sleep 3
pgrep -f "[p]deep.py|[p]h_batch.py" >/dev/null && echo UNPARK_OK || echo UNPARK_STARTING'
started=0
for slot in "${slots[@]}"; do
  fleet_slot_is_frozen "$slot" && { echo "skip_frozen slot=$slot"; continue; }
  [[ " ${UPVOTE_SLOTS} ${LIVE_SLOTS} " == *" $slot "* ]] && { echo "skip_special slot=$slot"; continue; }
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  if [[ "$st" == TERMINATED || "$st" == STOPPED ]]; then
    echo "start slot=$slot name=$name"
    "${GC[@]}" compute instances start "$name" --zone="$ZONE" --quiet
    started=$((started + 1))
    # wait until RUNNING (max ~3 min)
    for _ in $(seq 1 36); do
      st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
      [[ "$st" == RUNNING ]] && break
      sleep 5
    done
  elif [[ "$st" != RUNNING ]]; then
    echo "skip slot=$slot status=$st"
    continue
  fi
  go="pdeep:fleet-${RUN_ID}-unpark-${TS}-${slot}"
  if [[ -f "$ART/upvote_go.token" ]] && [[ " ${UPVOTE_SLOTS} " == *" $slot "* ]]; then
    go="$(tr -d '\n' <"$ART/upvote_go.token")"
  fi
  echo "$go" | "${GC[@]}" storage cp - "${VM_GCS}/GO.${name}" >/dev/null 2>&1 || true
  "${GC[@]}" compute instances add-metadata "$name" --zone="$ZONE" \
    --metadata-from-file "ph-strategy-env=$STRATEGY" --quiet 2>/dev/null || true
  "${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet \
    --ssh-flag=-oConnectTimeout=25 </dev/null --command="$REMOTE_BOOT" 2>/dev/null | sed "s/^/slot=$slot /" &
  if ((started % 4 == 0)); then wait || true; fi
done
wait || true
echo "unpark_done started_new=$started"