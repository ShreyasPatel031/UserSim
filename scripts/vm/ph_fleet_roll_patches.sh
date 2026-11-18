#!/usr/bin/env bash
# Push overlays + strategy to every running fleet VM, write the pdeep GO token, restart phsuper (kills the old batch
# and its browsers; the supervisor relaunches on the new token). ONLY_SLOTS="25 26" limits the roll.
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
STRATEGY="${PH_FLEET_STRATEGY_ENV:-$ROOT/scripts/vm/ph_strategies/fleet_optimize.env}"
D="$ROOT/scripts/vm/reuse_overlays"
# Never inherit PH_GO_MODE from upvote_refresh in the parent shell (that pushed repullupvotes GO fleet-wide).
# Per-slot GO tokens only (bare pdeep:fleet-{run_id} and legacy -rN experiment tokens break instant-exit loops).
GO_TOKEN_PREFIX="pdeep:fleet-${RUN_ID}-orch-roll"
UPVOTE_SLOTS="${FLEET_UPVOTE_SLOTS:-${UPVOTE_SLOTS:-9 27 38}}"
FLEET_LIVE_SLOTS="${FLEET_LIVE_SLOTS:-39}"
UPVOTE_GO=""
UPVOTE_STRATEGY="${PH_UPVOTE_STRATEGY_ENV:-$ROOT/scripts/vm/ph_strategies/fleet_upvote_refresh.env}"
[[ -f "$ART/upvote_go.token" ]] && UPVOTE_GO="$(tr -d '\n' <"$ART/upvote_go.token")"
[[ -z "$UPVOTE_GO" ]] && UPVOTE_GO="repullupvotes:fleet-upvote-${RUN_ID}"

if [[ "${SKIP_UPLOAD:-0}" != 1 ]]; then
  "${GC[@]}" storage cp "$D"/*.py "$D/supervisor_strat.sh" "$D/ensure_geoip.sh" "$D/proxy_geo_sync.sh" "${OVERLAY_GCS}/"
  "${GC[@]}" storage cp "$STRATEGY" "${OVERLAY_GCS}/fleet_optimize.env"
fi

REMOTE_CMD='set -e
B=$(grep -E "^PACE_GCS_VM_ROOT=" /opt/ph/pace.env | cut -d= -f2-)
TMP=/tmp/ph-overlay-roll
rm -rf "$TMP" && mkdir -p "$TMP"
gcloud storage cp -q "$B/_code/overlays/*.py" "$B/_code/overlays/supervisor_strat.sh" "$B/_code/overlays/ensure_geoip.sh" "$B/_code/overlays/proxy_geo_sync.sh" "$B/_code/overlays/fleet_optimize.env" "$TMP/" 2>/dev/null || true
sudo cp -f "$TMP"/*.py /opt/ph/overlays/ 2>/dev/null || true
[[ -s "$TMP/supervisor_strat.sh" ]] && sudo install -m 755 "$TMP/supervisor_strat.sh" /opt/ph/overlays/supervisor_strat.sh
[[ -s "$TMP/ensure_geoip.sh" ]] && sudo install -m 755 "$TMP/ensure_geoip.sh" /opt/ph/overlays/ensure_geoip.sh
[[ -s "$TMP/proxy_geo_sync.sh" ]] && sudo install -m 755 "$TMP/proxy_geo_sync.sh" /opt/ph/overlays/proxy_geo_sync.sh
[[ -x /opt/ph/overlays/proxy_geo_sync.sh ]] && { B=$(grep -E "^PACE_GCS_VM_ROOT=" /opt/ph/pace.env | cut -d= -f2-); PACE_GCS_VM_ROOT="$B" bash /opt/ph/overlays/proxy_geo_sync.sh >>/opt/ph/reuse/supervisor.log 2>&1 || true; }
if [[ -x /opt/venv/bin/python ]]; then
  for _p in patch_upvotes_ph_end.py patch_fix_ph_batch_syntax.py; do
    [[ -f /opt/ph/overlays/$_p ]] && sudo /opt/venv/bin/python /opt/ph/overlays/$_p /opt/ph/reuse >>/opt/ph/reuse/supervisor.log 2>&1 || true
  done
  sudo /opt/venv/bin/python -m py_compile /opt/ph/reuse/ph_batch.py 2>>/opt/ph/reuse/supervisor.log || true
fi
sudo cp -f "$TMP/fleet_optimize.env" /opt/ph/strategy.env 2>/dev/null || true
sudo rm -f /opt/ph/reuse/cf_cooldown_until /opt/ph/reuse/same_tok_retry_at /opt/ph/reuse/cf_backoff_n 2>/dev/null || true
if [[ "${PRESERVE_QUEUE_CACHE:-0}" != 1 ]]; then
  sudo rm -f /opt/ph/reuse/KICK /opt/ph/reuse/last_token /tmp/pdeep_queue_cache.json /opt/ph/reuse/pdeep_queue_cache.json /opt/ph/reuse/port_override 2>/dev/null || true
else
  sudo rm -f /opt/ph/reuse/KICK /opt/ph/reuse/last_token /opt/ph/reuse/port_override 2>/dev/null || true
fi
sudo systemctl stop phsuper || true
sudo pkill -f "[p]deep.py|[p]h_batch.py" 2>/dev/null || true; sudo pkill -f "[c]amoufox" 2>/dev/null || true; sudo pkill -f "[p]laywright/driver" 2>/dev/null || true
EA=""; [[ -f /opt/ph/pace.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/pace.env"; [[ -f /opt/ph/strategy.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/strategy.env"
sudo systemd-run --unit=phsuper --collect -p WorkingDirectory=/opt/ph/reuse $EA /bin/bash -c "bash /opt/ph/overlays/supervisor_strat.sh >> /opt/ph/reuse/supervisor.log 2>&1" >/dev/null 2>&1
sleep 1; systemctl is-active phsuper >/dev/null
echo ROLL_OK'

while IFS=$'\t' read -r slot _port; do
  [[ -z "$slot" || "$slot" == \#* ]] && continue
  if [[ -n "${ONLY_SLOTS:-}" && " ${ONLY_SLOTS} " != *" $slot "* ]]; then continue; fi
  if [[ " ${FLEET_LIVE_SLOTS} " == *" $slot "* ]]; then
    echo "==> skip live slot $slot"
    continue
  fi
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$PACE_ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || continue
  (
    slot_go="${GO_TOKEN_PREFIX}-$(date +%s)-${slot}"
    slot_strat="$STRATEGY"
    if [[ " ${UPVOTE_SLOTS} " == *" $slot "* ]]; then
      slot_go="$UPVOTE_GO"
      slot_strat="$UPVOTE_STRATEGY"
    fi
    "${GC[@]}" compute instances add-metadata "$name" --zone="$PACE_ZONE" \
      --metadata-from-file="ph-strategy-env=$slot_strat" >/dev/null 2>&1 || true
    echo "$slot_go" | "${GC[@]}" storage cp - "${VM_GCS}/GO.${name}" >/dev/null 2>&1 || true
    r="$("${GC[@]}" compute ssh "$name" --zone="$PACE_ZONE" --tunnel-through-iap --quiet --ssh-flag=-oConnectTimeout=15 \
      </dev/null --command="$REMOTE_CMD" 2>/dev/null | tail -1 || true)"
    echo "==> roll $name ${r:-SSH_FAIL}"
  ) &
  while (( $(jobs -rp | wc -l) >= ${ROLL_PAR:-8} )); do sleep 1; done
done <"$ART/slots.tsv"
wait
