#!/usr/bin/env bash
# Deploy N IPRoyal dedicated IPs: 1 VM each, wipe stale Camoufox geo fingerprints, L3_mid.
#   export PACE_FLEET_RUN_ID=20261108t082000z FLEET_MAX_VMS=5
#   ./scripts/vm/ph_iproyal_sync_pool.sh
#   ./scripts/vm/ph_iproyal_deploy_fleet.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PATH="/home/ubuntu/google-cloud-sdk/bin:${PATH:-}"
# shellcheck source=/dev/null
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}" 2>/dev/null || true
PROJECT="${GCP_PROJECT:?}"
BUCKET="${MVP_GCS_BUCKET:?}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:-$("${GC[@]}" compute instances list --project="$PROJECT" --filter='name~feeder-fleet' --limit=1 --format='value(zone)')}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
POOL="${PACE_IPROYAL_POOL:-$ROOT/secrets/iproyal.pool}"
N="${IPROYAL_FLEET_N:-5}"
LEVEL="${IPROYAL_FLEET_LEVEL:-L3_mid}"

_purl_abs() { local p=$1; [[ "$p" = /* ]] && echo "$p" || echo "$ROOT/$p"; }

merge_env() {
  local out="$ROOT/results/ph_iproyal_limit/strategy_${LEVEL}.env"
  mkdir -p "$(dirname "$out")"
  {
    cat "$ROOT/scripts/vm/ph_strategies/iproyal/_base.env"
    echo
    cat "$ROOT/scripts/vm/ph_strategies/iproyal/${LEVEL}.env"
    if [[ -f "$ROOT/scripts/vm/ph_strategies/fleet_iproyal.env" ]]; then
      echo
      echo "# fleet_iproyal queue/tabs (IPRoyal ops)"
      grep -E '^(PH_TABS|PH_BROWSER_TABS|PH_MAX_INFLIGHT|PH_RAMP|PH_REQ_PER_MIN|PDEEP_|PH_RR)' \
        "$ROOT/scripts/vm/ph_strategies/fleet_iproyal.env" || true
    fi
  } >"$out"
  echo "$out"
}

read_pool() {
  mapfile -t PURLS < <(grep -v '^[[:space:]]*#' "$POOL" | grep -v '^[[:space:]]*$' || true)
  ((${#PURLS[@]} >= 1)) || { echo "missing $POOL — run ph_iproyal_sync_pool.sh" >&2; exit 1; }
  N=$(( N < ${#PURLS[@]} ? N : ${#PURLS[@]} ))
}

wipe_profiles() {
  local slot="${1:?wipe_profiles needs slot}"
  local name="feeder-fleet-${RUN_ID}-${slot}"
  "${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet </dev/null \
    --command='sudo rm -rf /opt/ph/profiles/* /opt/ph/reuse/.strat_cleaned 2>/dev/null; sudo mkdir -p /opt/ph/profiles; FORCE_GEOIP_REFRESH=1 PACE_GCS_VM_ROOT="'"${PACE_GCS_VM_ROOT:-gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"'" sudo -E bash /opt/ph/overlays/ensure_geoip.sh 2>/dev/null || true; sudo systemctl restart phsuper 2>/dev/null || true' \
    2>/dev/null || echo "wipe skipped $name (ssh)"
}

bind_slot() {
  local slot=$1 purl
  purl="$(_purl_abs "$2")"
  local name="feeder-fleet-${RUN_ID}-${slot}" strat
  strat="$(merge_env)"
  [[ -f "$purl" ]] || { echo "missing $purl" >&2; exit 1; }
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || { echo "skip $name status=$st"; return 0; }
  "${GC[@]}" compute instances add-metadata "$name" --zone="$ZONE" \
    --metadata-from-file="proxy-url=$purl,ph-strategy-env=$strat" >/dev/null
  echo "bound slot=$slot ip=$(python3 -c "import urllib.parse as u; print(u.urlparse(open('$purl').read().strip()).hostname)")"
}

mkdir -p "$ART"
cat >"$ART/pace.env" <<EOF
MVP_GCS_BUCKET=${BUCKET}
PACE_GCS_VM_ROOT=gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm
PH_OVERLAYS_DIR=/opt/ph/overlays
PH_PROXY_FIXED_PORT=1
PH_PORTSCREEN_HOME_ONLY=1
PH_PORTSCREEN_MAX_TRY=1
EOF

read_pool
STRAT="$(merge_env)"
export PACE_PROXY_FILE="$(_purl_abs "${PURLS[0]}")" PH_FLEET_STRATEGY="$STRAT" PACE_TEMPLATE="${PACE_TEMPLATE:-pace-feeder-e2-standard-2}"
FLEET_MIN_VMS=0 FLEET_MAX_VMS="$N" PACE_FLEET_RUN_ID="$RUN_ID" bash "$ROOT/scripts/vm/ph_fleet_autoscale.sh" scale-to "$N"
ONLY_SLOTS="$(seq -s, 1 "$N")" PH_FLEET_STRATEGY_ENV="$STRAT" bash "$ROOT/scripts/vm/ph_fleet_roll_patches.sh" | tail -5

for i in $(seq 1 "$N"); do
  bind_slot "$i" "${PURLS[$((i - 1))]}"
done
ONLY_SLOTS="$(seq -s, 1 "$N")" PH_FLEET_STRATEGY_ENV="$STRAT" bash "$ROOT/scripts/vm/ph_fleet_roll_patches.sh" | tail -3

for i in $(seq 1 "$N"); do
  wipe_profiles "$i"
done
echo "deployed $N feeders; warmed 180s for geo+fingerprint..."
sleep 180
ART_OUT="$ROOT/results/ph_iproyal_limit/fleet_deploy_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ART_OUT"
for i in $(seq 1 "$N"); do
  name="feeder-fleet-${RUN_ID}-${i}"
  line="$("${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet </dev/null --command="python3 -c \"
import json,socket,time
from datetime import datetime,timezone
W=480;now=time.time();p=f'/opt/ph/reuse/status_{socket.gethostname()}.jsonl'
rows=open(p).read().splitlines() if __import__('os').path.isfile(p) else []
nc=bo=bf=0;ip=None
for ln in rows:
  try:j=json.loads(ln)
  except:continue
  t=datetime.fromisoformat((j.get('utc')or'').replace('Z','+00:00')).timestamp() if j.get('utc') else 0
  if j.get('event')=='exit_ip' and t and now-t<W: ip=j.get('exit_ip')
  if j.get('event')=='browser_open' and t and now-t<W:
    if j.get('ok') is False: bf+=1
    else: bo+=1
  if not t or now-t>W: continue
  if j.get('handle') and j.get('rc')==0: nc+=1
print(json.dumps({'slot':$i,'exit_ip':ip,'complete_8m':nc,'browser_ok':bo,'browser_fail':bf}))
\"" 2>/dev/null || echo '{"ssh_fail":true}')"
  echo "slot $i $line" | tee -a "$ART_OUT/slots.jsonl"
done
echo "results $ART_OUT"
