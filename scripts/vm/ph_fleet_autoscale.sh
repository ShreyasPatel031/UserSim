#!/usr/bin/env bash
# Autoscale feeder-fleet to keep fleet people/min in [TARGET_LO, TARGET_HI].
#   ./scripts/vm/ph_fleet_autoscale.sh status
#   ./scripts/vm/ph_fleet_autoscale.sh scale-to 20
#   ./scripts/vm/ph_fleet_autoscale.sh loop
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT="${GCP_PROJECT:?}"
ZONE="${PACE_ZONE:?}"
BUCKET="${MVP_GCS_BUCKET:?}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${PROJECT}.iam.gserviceaccount.com}"
[[ -d /home/ubuntu/google-cloud-sdk/bin ]] && export PATH="/home/ubuntu/google-cloud-sdk/bin:$PATH"
GC=(gcloud --account="$SA")
FLEET="$ROOT/scripts/vm/ph_fleet_full_experiment.sh"
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt" 2>/dev/null || true)}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
TARGET_LO="${FLEET_TARGET_LO:-20}"
TARGET_HI="${FLEET_TARGET_HI:-30}"
MAX_VMS="${FLEET_MAX_VMS:-30}"
MIN_VMS="${FLEET_MIN_VMS:-4}"
MACHINE="${PH_FLEET_MACHINE:-e2-standard-2}"
# On-demand e2-standard-2 list price ~$0.06701/hr (STANDARD provisioning).
HOURLY_USD="${FLEET_HOURLY_USD:-0.06701}"
PROXY_FILE="${PACE_PROXY_FILE:-$ROOT/.purl}"
STRATEGY_ENV="${PH_FLEET_STRATEGY:-$ROOT/scripts/vm/ph_strategies/fleet_optimize.env}"
PORT_PREFIX="${PACE_PORT_REGISTRY_PREFIX:-gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm/_ports}"
VM_GCS="${PACE_VM_GCS:-gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"
COMMON_META="pkg-name=bsit_full17.tgz;pkg-md5=Ku9PrVAfo8f+uDrIVfW8Bg==;k-levels=1,1;pace-state=0 600 0"
NEVER_PORTS=(10001 10005 10006 10020)

vm_name() { echo "feeder-fleet-${RUN_ID}-${1}"; }

next_port() {
  local taken p
  taken="$("${GC[@]}" storage ls "${PORT_PREFIX}/" 2>/dev/null | sed -n 's/.*port\.\([0-9]*\).*/\1/p' | sort -nu)"
  for p in $(seq 10000 20000); do
    printf '%s\n' "${NEVER_PORTS[@]}" | grep -qx "$p" && continue
    echo "$taken" | grep -qx "$p" && continue
    # also skip ports already in slots.tsv
    awk -F'\t' '{print $2}' "$ART/slots.tsv" 2>/dev/null | grep -qx "$p" && continue
    echo "$p"; return 0
  done
  return 1
}

n_slots() { awk 'NF>=2 && $1+0==$1' "$ART/slots.tsv" 2>/dev/null | wc -l; }

# Probe one VM → "slot\tjson\tppm\twarm(0|1)". Parallelized by sample_fleet_ppm.
_probe_slot() {
  local slot=$1 name line
  name="feeder-fleet-${RUN_ID}-${slot}"
  line="$(gcloud --account="$SA" compute ssh "$name" --zone="$ZONE" --project="$PROJECT" \
    --tunnel-through-iap --quiet \
    --ssh-flag="-o ConnectTimeout=10" --ssh-flag="-o StrictHostKeyChecking=no" \
    </dev/null --command="python3 -c \"
import json
from pathlib import Path
from datetime import datetime, timezone
n=len([p for p in Path('/opt/ph/reuse/out').glob('*.json') if p.name!='hb.json']) if Path('/opt/ph/reuse/out').exists() else 0
fp=None
p=Path('/opt/ph/reuse/setup_timing.jsonl')
for ln in (p.read_text().splitlines() if p.exists() else []):
  try: j=json.loads(ln)
  except Exception: continue
  if j.get('event')=='first_pull': fp=j.get('utc')
if not fp:
  print(n, 0, 0); raise SystemExit
t=datetime.fromisoformat(fp.replace('Z','+00:00'))
sec=max(60.0,(datetime.now(timezone.utc)-t).total_seconds())
print(n, round(n*60.0/sec,4), 1)
\"" 2>/dev/null | grep -E '^[0-9]' | tail -1)" || line="0 0 0"
  read -r n ppm warm <<<"$line" || true
  printf '%s\t%s\t%s\t%s\n' "$slot" "${n:-0}" "${ppm:-0}" "${warm:-0}"
}

sample_fleet_ppm() {
  # Parallel SSH probes. Report: alive  json_sum  fleet_ppm  warm_n  avg_warm_ppm
  # fleet_ppm = avg(warm_ppm) * n_slots  (steady-state projection; warming VMs not zeroed)
  local slots=() tmp alive warm_n=0 json_sum=0 avg=0 fleet=0
  alive=$(n_slots)
  mapfile -t slots < <(awk -F'\t' 'NF>=2 && $1+0==$1 {print $1}' "$ART/slots.tsv")
  tmp="$(mktemp)"
  export -f _probe_slot
  export SA ZONE PROJECT RUN_ID
  printf '%s\n' "${slots[@]}" | xargs -P 8 -I{} bash -c '_probe_slot "$@"' _ {} >"$tmp" 2>/dev/null || true
  while IFS=$'\t' read -r _slot n ppm warm; do
    [[ -z "${_slot:-}" ]] && continue
    json_sum=$((json_sum + ${n:-0}))
    if [[ "${warm:-0}" == "1" ]]; then
      warm_n=$((warm_n + 1))
      avg=$(python3 -c "print(float('$avg') + float('${ppm:-0}'))")
    fi
  done <"$tmp"
  rm -f "$tmp"
  if [[ $warm_n -gt 0 ]]; then
    avg=$(python3 -c "print(round(float('$avg') / $warm_n, 4))")
    fleet=$(python3 -c "print(round(float('$avg') * $alive, 4))")
  else
    avg=0
    fleet=0
  fi
  echo -e "${alive}\t${json_sum}\t${fleet}\t${warm_n}\t${avg}"
}

create_one() {
  local slot=$1 port=$2
  local name meta
  name="$(vm_name "$slot")"
  meta="^;^proxy-port=${port};${COMMON_META};fleet-slot=${slot}"
  echo "==> create $name port=$port"
  "${GC[@]}" compute instances create "$name" \
    --project="$PROJECT" --zone="$ZONE" \
    --machine-type="$MACHINE" \
    --network=main-vpc --subnet=primary-subnet \
    --image-family=pace-feeder --image-project="$PROJECT" --boot-disk-size=20GB \
    --service-account="$SA" --scopes=cloud-platform \
    --tags=allow-iap-ssh \
    --metadata-from-file "proxy-url=$PROXY_FILE,ph-strategy-env=$STRATEGY_ENV,pace-boot-env=$ART/pace.env,startup-script=$ROOT/pace_startup.sh" \
    --metadata "$meta" \
    || "${GC[@]}" compute instances create "$name" \
      --project="$PROJECT" --zone="$ZONE" \
      --machine-type="$MACHINE" \
      --network=main-vpc --subnet=primary-subnet \
      --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=20GB \
      --service-account="$SA" --scopes=cloud-platform \
      --tags=allow-iap-ssh \
      --metadata-from-file "proxy-url=$PROXY_FILE,ph-strategy-env=$STRATEGY_ENV,pace-boot-env=$ART/pace.env,startup-script=$ROOT/pace_startup.sh" \
      --metadata "$meta"
  printf '%s fleet-%s\n' "$name" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" |
    "${GC[@]}" storage cp - "${PORT_PREFIX}/port.${port}"
  echo "run:fleet-${RUN_ID}" | "${GC[@]}" storage cp - "${VM_GCS}/GO.$name"
}

delete_one() {
  local slot=$1
  local port name
  port="$(awk -F'\t' -v s="$slot" '$1==s{print $2;exit}' "$ART/slots.tsv")"
  name="$(vm_name "$slot")"
  echo "==> delete $name"
  "${GC[@]}" compute instances delete "$name" --zone="$ZONE" --project="$PROJECT" --quiet || true
  [[ -n "$port" ]] && "${GC[@]}" storage rm "${PORT_PREFIX}/port.${port}" 2>/dev/null || true
  awk -F'\t' -v s="$slot" '$1!=s' "$ART/slots.tsv" >"$ART/slots.tsv.tmp" && mv "$ART/slots.tsv.tmp" "$ART/slots.tsv"
}

cmd_scale_to() {
  local want=$1 have next port
  have=$(n_slots)
  echo "scale-to $want (have $have)"
  while [[ $(n_slots) -lt $want ]]; do
    next=$(awk -F'\t' 'NF>=2 && $1+0==$1 {m=$1} END{print m+1}' "$ART/slots.tsv")
    port="$(next_port)"
    echo -e "${next}\t${port}" >>"$ART/slots.tsv"
    create_one "$next" "$port"
  done
  while [[ $(n_slots) -gt $want ]]; do
    next=$(awk -F'\t' 'NF>=2 && $1+0==$1 {m=$1} END{print m}' "$ART/slots.tsv")
    [[ "$next" -le $MIN_VMS ]] && break
    delete_one "$next"
  done
}

write_snapshot() {
  local alive json ppm warm_n avg n cost_hr cost_day
  IFS=$'\t' read -r alive json ppm warm_n avg <<<"$(sample_fleet_ppm)"
  n=$(n_slots)
  cost_hr=$(python3 -c "print(round($n * $HOURLY_USD, 4))")
  cost_day=$(python3 -c "print(round($n * $HOURLY_USD * 24, 2))")
  mkdir -p "$ART"
  python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path
p=Path("$ART/dashboard_snapshot.json")
snap={
  "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
  "run_id": "$RUN_ID",
  "vms": int("$n"),
  "alive_pulling_est": int("$alive"),
  "json_sum": int("$json"),
  "fleet_ppm": float("$ppm" or 0),
  "warm_vms": int("$warm_n" or 0),
  "ppm_per_warm_vm": float("$avg" or 0),
  "target_lo": float("$TARGET_LO"),
  "target_hi": float("$TARGET_HI"),
  "machine": "$MACHINE",
  "hourly_usd_per_vm": float("$HOURLY_USD"),
  "compute_usd_per_hour": float("$cost_hr"),
  "compute_usd_per_day": float("$cost_day"),
  "slots": [ln.strip().split("\t") for ln in Path("$ART/slots.tsv").read_text().splitlines() if ln.strip() and not ln.startswith("#")],
}
p.write_text(json.dumps(snap, indent=2))
print(json.dumps(snap))
Path("$ART/autoscale.jsonl").open("a").write(json.dumps(snap)+"\n")
PY
}

cmd_autoscale_once() {
  local alive json ppm warm_n avg n realized need desired
  export FLEET_ART="$ART" PACE_FLEET_RUN_ID="$RUN_ID"
  if [[ -f "$ROOT/scripts/vm/ph_fleet_measure.py" ]]; then
  realized="$(python3 "$ROOT/scripts/vm/ph_fleet_measure.py" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('realized_ppm',0))" 2>/dev/null || echo 0)"
  need="$(python3 -c "import json; print(json.load(open('$ART/fleet_measure.json')).get('vms_needed_for_20',24))" 2>/dev/null || echo 24)"
  else
  realized=0; need=24
  fi
  # Single sample → snapshot + decision (avoid double SSH sweep)
  IFS=$'\t' read -r alive json ppm warm_n avg <<<"$(sample_fleet_ppm)"
  n=$(n_slots)
  cost_hr=$(python3 -c "print(round($n * $HOURLY_USD, 4))")
  cost_day=$(python3 -c "print(round($n * $HOURLY_USD * 24, 2))")
  python3 - <<PY >"$ART/last_snapshot.json"
import json
from datetime import datetime, timezone
from pathlib import Path
snap={
  "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
  "run_id": "$RUN_ID",
  "vms": int("$n"),
  "alive_pulling_est": int("$alive"),
  "json_sum": int("$json"),
  "fleet_ppm": float("$ppm" or 0),
  "warm_vms": int("$warm_n" or 0),
  "ppm_per_warm_vm": float("$avg" or 0),
  "target_lo": float("$TARGET_LO"),
  "target_hi": float("$TARGET_HI"),
  "machine": "$MACHINE",
  "hourly_usd_per_vm": float("$HOURLY_USD"),
  "compute_usd_per_hour": float("$cost_hr"),
  "compute_usd_per_day": float("$cost_day"),
}
Path("$ART/dashboard_snapshot.json").write_text(json.dumps(snap, indent=2))
Path("$ART/autoscale.jsonl").open("a").write(json.dumps(snap)+"\n")
print(json.dumps(snap))
PY
  read -r cold_vms active_vms productive_vms <<<"$(python3 -c "
import json
m=json.load(open('$ART/fleet_measure.json'))
print(m.get('cold_vms',0), m.get('active_vms',0), m.get('productive_vms',0))
" 2>/dev/null || echo "0 0 0")"
  desired=$(python3 -c "
import json
m=json.load(open('$ART/fleet_measure.json'))
r=float('$realized' or 0)
lo=float('$TARGET_LO')
need=int('$need')
n=int('$n')
prod=int('$productive_vms' or 0)
# Target VM count: enough productive headroom, not 'need' when half the fleet is CF-wall.
if r >= lo:
    d=max($MIN_VMS, min(n, max(prod + 2, int(need))))
else:
    d=max($MIN_VMS, min($MAX_VMS, prod + 4 if prod else $MIN_VMS))
print(d)
")
  use_ppm="${realized:-$ppm}"
  echo "realized=$use_ppm cold=$cold_vms active=$active_vms prod=$productive_vms vms=$n desired=$desired target=[$TARGET_LO,$TARGET_HI] \$${cost_day}/day"
  # Shed idle: drop highest slots stuck on CF wall when over desired
  idle_drop="$(python3 -c "
import json
rows=json.load(open('$ART/fleet_measure.json')).get('slots',[])
cand=sorted([r['slot'] for r in rows if r.get('state') in ('cf_wall','cold','dead','probe_fail') and (r.get('n') or 0)<=2], reverse=True)
drop=max(0, int('$n')-int('$desired'))
print(' '.join(str(s) for s in cand[:drop]))
" 2>/dev/null || true)"
  if [[ -n "$idle_drop" ]]; then
    for slot in $idle_drop; do
      echo "SHED idle slot $slot"
      delete_one "$slot" || true
    done
    n=$(n_slots)
  fi
  if python3 -c "import sys; sys.exit(0 if float('$use_ppm') < float('$TARGET_LO') else 1)"; then
    if [[ "${cold_vms:-0}" -gt "${active_vms:-0}" ]]; then
      echo "HOLD scale-up — cold($cold_vms) > active($active_vms); shed/restart only"
    elif [[ $n -lt $desired && $n -lt $MAX_VMS ]]; then
      echo "UNDER target → +1 VM (cap $MAX_VMS)"
      cmd_scale_to $((n + 1))
    else
      echo "UNDER — hold $n VMs until more pullers warm"
    fi
  elif python3 -c "import sys; sys.exit(0 if float('$use_ppm') > float('$TARGET_HI') else 1)"; then
    if [[ $n -gt $desired && $n -gt $MIN_VMS ]]; then
      echo "OVER target → scale toward $desired"
      cmd_scale_to "$desired"
    fi
  else
    echo "IN BAND — hold $n VMs"
  fi
}

cmd_status() {
  write_snapshot
}

# Serialize create/delete so concurrent once+loop cannot race.
with_scale_lock() {
  local lock="$ART/autoscale.lock"
  mkdir -p "$ART"
  exec 9>"$lock"
  if ! flock -n 9; then
    echo "another autoscale holds $lock — skip"
    return 0
  fi
  "$@"
}

case "${1:-}" in
  status) cmd_status ;;
  scale-to) with_scale_lock cmd_scale_to "${2:?n}" ;;
  once) with_scale_lock cmd_autoscale_once ;;
  loop)
    while true; do
      with_scale_lock cmd_autoscale_once || true
      sleep "${FLEET_AUTOSCALE_SEC:-600}"
    done
    ;;
  *) echo "usage: $0 status|scale-to N|once|loop" >&2; exit 1 ;;
esac
