#!/usr/bin/env bash
# Four-VM fleet: full ph_batch extraction from live queue, aggressive scale_down @ 32 tabs.
# Keeper deletes/recreates VMs after 403, crash, or stall (new disk = new fingerprint; same sticky port).
#
#   export GCP_PROJECT PACE_ZONE MVP_GCS_BUCKET
#   ./scripts/vm/ph_fleet_full_experiment.sh up --fetch-proxy-from feeder-phpeople-1
#   ./scripts/vm/ph_fleet_full_experiment.sh keeper --loop    # run in tmux alongside monitor
#   ./scripts/vm/ph_fleet_full_experiment.sh monitor --loop
#   ./scripts/vm/ph_fleet_full_experiment.sh summary
#   ./scripts/vm/ph_fleet_full_experiment.sh down
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT="${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:-}}"
ZONE="${PACE_ZONE:?export PACE_ZONE}"
[[ -n "$PROJECT" ]] || { echo "set GCP_PROJECT" >&2; exit 1; }
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${PROJECT}.iam.gserviceaccount.com}"
[[ -d /home/ubuntu/google-cloud-sdk/bin ]] && export PATH="/home/ubuntu/google-cloud-sdk/bin:$PATH"
GC=(gcloud --account="$SA")
BUCKET="${MVP_GCS_BUCKET:?export MVP_GCS_BUCKET}"
PORT_PREFIX="${PACE_PORT_REGISTRY_PREFIX:-gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm/_ports}"
VM_GCS="${PACE_VM_GCS:-gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"
OVERLAY_GCS="${VM_GCS}/_code/overlays"
PROXY_FILE="${PACE_PROXY_FILE:-$ROOT/.purl}"
NEVER_PORTS=(10001 10005 10006 10020)
STRATEGY_ENV="${PH_FLEET_STRATEGY:-$ROOT/scripts/vm/ph_strategies/fleet_aggressive.env}"
SLOTS=(1 2 3 4)
MACHINE="${PH_FLEET_MACHINE:-e2-standard-2}"
KEEPER_DOWN_SEC="${KEEPER_DOWN_SEC:-1800}"       # replace VM missing/stopped ≥30 min
KEEPER_STALL_SEC="${KEEPER_STALL_SEC:-1800}"     # no new JSON while RUNNING ≥30 min
KEEPER_BLOCK_COOLDOWN_SEC="${KEEPER_BLOCK_COOLDOWN_SEC:-360}"  # after 403, wait then recreate
COMMON_META="pkg-name=bsit_full17.tgz;pkg-md5=Ku9PrVAfo8f+uDrIVfW8Bg==;k-levels=1,1;pace-state=0 600 0"
TEMPLATE="${PACE_TEMPLATE:-}"
INTERVAL_SEC="${INTERVAL_SEC:-300}"
DURATION_SEC="${DURATION_SEC:-14400}"
RUN_ID="${PACE_FLEET_RUN_ID:-${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}}"
RUN_ID="${RUN_ID,,}"
ART="${ROOT}/results/ph_fleet_full/${RUN_ID}"
GO_TOKEN="run:fleet-${RUN_ID}"

upload_overlays() {
  local d="$ROOT/scripts/vm/reuse_overlays"
  "${GC[@]}" storage cp \
    "$d/supervisor_strat.sh" "$d/portscreen.py" "$d/strategy_args.py" \
    "$d/setup_probe.py" "$d/ensure_geoip.sh" \
    "$d/patch_week_bytes.py" "$d/patch_stop_first_block.py" \
    "${OVERLAY_GCS}/"
  "${GC[@]}" storage cp "$STRATEGY_ENV" "${OVERLAY_GCS}/fleet_aggressive.env"
  echo "Overlays -> ${OVERLAY_GCS}/"
}

write_boot_env() {
  cat >"$ART/pace.env" <<EOF
MVP_GCS_BUCKET=${BUCKET}
PACE_GCS_VM_ROOT=${VM_GCS}
PH_OVERLAYS_DIR=/opt/ph/overlays
PH_PORTSCREEN_HOME_ONLY=1
PH_PORTSCREEN_MAX_TRY=1
EOF
}

vm_name() { echo "feeder-fleet-${RUN_ID}-${1}"; }

next_port() {
  local taken p
  taken="$("${GC[@]}" storage ls "${PORT_PREFIX}/" 2>/dev/null | sed -n 's/.*port\.\([0-9]*\).*/\1/p' | sort -nu)"
  for p in $(seq 10000 20000); do
    printf '%s\n' "${NEVER_PORTS[@]}" | grep -qx "$p" && continue
    echo "$taken" | grep -qx "$p" && continue
    echo "$p"
    return 0
  done
  echo "no free sticky port" >&2
  return 1
}

fetch_proxy() {
  local vm=$1
  export PROXY_FILE
  "${GC[@]}" compute instances describe "$vm" --zone="$ZONE" --project="$PROJECT" --format=json |
    python3 -c "
import json,sys,os
j=json.load(sys.stdin)
out=os.environ['PROXY_FILE']
for it in j.get('metadata',{}).get('items',[]) or []:
    if it.get('key')=='proxy-url' and (it.get('value') or '').strip():
        open(out,'w').write(it['value'].strip()+'\n'); sys.exit(0)
sys.exit(1)
"
  chmod 600 "$PROXY_FILE"
}

create_vm() {
  local slot=$1 port=$2
  local name
  name="$(vm_name "$slot")"
  local meta="^;^proxy-port=${port};${COMMON_META};fleet-slot=${slot}"
  local create_args=(
    --project="$PROJECT" --zone="$ZONE"
    --machine-type="$MACHINE"
    --network=main-vpc --subnet=primary-subnet
    --boot-disk-size=20GB
    --service-account="$SA" --scopes=cloud-platform
    --tags=allow-iap-ssh
    --metadata-from-file "proxy-url=$PROXY_FILE,ph-strategy-env=$STRATEGY_ENV,pace-boot-env=$ART/pace.env,startup-script=$ROOT/pace_startup.sh"
    --metadata "$meta"
  )
  if [[ -n "$TEMPLATE" ]]; then
    "${GC[@]}" compute instances create "$name" \
      --source-instance-template="$TEMPLATE" "${create_args[@]}"
  else
    "${GC[@]}" compute instances create "$name" \
      --image-family=pace-feeder --image-project="$PROJECT" "${create_args[@]}" \
      || "${GC[@]}" compute instances create "$name" \
        --image-family=debian-12 --image-project=debian-cloud "${create_args[@]}"
  fi
  printf '%s fleet-%s\n' "$name" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" |
    "${GC[@]}" storage cp - "${PORT_PREFIX}/port.${port}"
}

write_go() {
  local slot=$1 token=$2
  echo "$token" | "${GC[@]}" storage cp - "${VM_GCS}/GO.$(vm_name "$slot")"
}

cmd_up() {
  local fetch_from=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --fetch-proxy-from) fetch_from=$2; shift 2 ;;
      *) echo "unknown: $1" >&2; exit 1 ;;
    esac
  done
  [[ -n "$fetch_from" ]] && fetch_proxy "$fetch_from"
  [[ -f "$PROXY_FILE" ]] || { echo "missing proxy; --fetch-proxy-from" >&2; exit 1; }
  [[ -f "$STRATEGY_ENV" ]] || { echo "missing $STRATEGY_ENV" >&2; exit 1; }
  mkdir -p "$ART"
  echo "$RUN_ID" >"${ROOT}/results/ph_fleet_full/latest_run.txt"
  write_boot_env
  upload_overlays
  : >"$ART/slots.tsv"
  echo '{"slots":{}}' >"$ART/keeper_state.json"
  for slot in "${SLOTS[@]}"; do
    port="$(next_port)"
    echo -e "${slot}\t${port}" >>"$ART/slots.tsv"
    echo "==> slot $slot $(vm_name "$slot") port=$port"
    create_vm "$slot" "$port"
    write_go "$slot" "$GO_TOKEN"
  done
  date -u +%Y-%m-%dT%H:%M:%SZ >"$ART/started_at.txt"
  echo -e "# ts\tslot\tvm\tstatus\tjson\tppm\tc403\tgen\tnote" >"$ART/samples.tsv"
  echo "RUN_ID=$RUN_ID artifacts=$ART machine=$MACHINE GO=$GO_TOKEN"
}

load_art() {
  if [[ -n "${PACE_FLEET_RUN_ID:-}" ]]; then
    RUN_ID="${PACE_FLEET_RUN_ID,,}"
  elif [[ -f "${ROOT}/results/ph_fleet_full/latest_run.txt" ]]; then
    RUN_ID="$(cat "${ROOT}/results/ph_fleet_full/latest_run.txt")"
  fi
  ART="${ROOT}/results/ph_fleet_full/${RUN_ID}"
  GO_TOKEN="run:fleet-${RUN_ID}"
}

slot_field() {
  local slot=$1 col=$2
  awk -F'\t' -v s="$slot" '$1==s {print $'"$col"'; exit}' "$ART/slots.tsv"
}

apply_patches_remote() {
  local name=$1
  "${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet </dev/null --command='
set -e
B=$(grep PACE_GCS_VM_ROOT /opt/ph/pace.env | cut -d= -f2-)
gcloud storage cp -q "$B/_code/overlays/patch_week_bytes.py" "$B/_code/overlays/patch_stop_first_block.py" /opt/ph/overlays/ 2>/dev/null || true
if [[ -x /opt/venv/bin/python && -f /opt/ph/reuse/ph_batch.py ]]; then
  /opt/venv/bin/python /opt/ph/overlays/patch_week_bytes.py 2>/dev/null || true
  /opt/venv/bin/python /opt/ph/overlays/patch_stop_first_block.py 2>/dev/null || true
fi
echo PATCH_OK
' 2>/dev/null || true
}

recreate_slot() {
  local slot=$1 reason=$2
  local port name token gen
  port="$(slot_field "$slot" 2)"
  name="$(vm_name "$slot")"
  gen=$(python3 -c "import json;print(json.load(open('$ART/keeper_state.json'))['slots'].get('$slot',{}).get('gen',0)+1)")
  token="${GO_TOKEN}-r${gen}"
  python3 - <<PY
import json
from pathlib import Path
p=Path("$ART/keeper_state.json")
st=json.loads(p.read_text())
st.setdefault("slots",{})["$slot"]={"gen":$gen,"last_recreate":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","reason":"$reason","token":"$token"}
p.write_text(json.dumps(st,indent=2))
PY
  echo "KEEPER recreate slot=$slot gen=$gen reason=$reason" | tee -a "$ART/keeper.log"
  "${GC[@]}" compute instances delete "$name" --zone="$ZONE" --project="$PROJECT" --quiet 2>/dev/null || true
  sleep 5
  create_vm "$slot" "$port"
  write_go "$slot" "$token"
  sleep 120
  apply_patches_remote "$name"
}

keeper_mark_down() {
  local slot=$1
  python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path
p = Path("$ART/keeper_state.json")
st = json.loads(p.read_text())
sl = st.setdefault("slots", {}).setdefault("$slot", {})
if not sl.get("down_since"):
    sl["down_since"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
p.write_text(json.dumps(st, indent=2))
PY
}

keeper_clear_down() {
  local slot=$1
  python3 - <<PY
import json
from pathlib import Path
p = Path("$ART/keeper_state.json")
st = json.loads(p.read_text())
sl = st.setdefault("slots", {}).setdefault("$slot", {})
sl.pop("down_since", None)
sl.pop("stall_since", None)
p.write_text(json.dumps(st, indent=2))
PY
}

keeper_secs_since() {
  local slot=$1 key=$2
  python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path
st = json.loads(Path("$ART/keeper_state.json").read_text())
t = st.get("slots", {}).get("$slot", {}).get("$key")
if not t:
    print(0)
else:
    print(int((datetime.now(timezone.utc) - datetime.fromisoformat(t.replace("Z", "+00:00"))).total_seconds()))
PY
}

keeper_note_json() {
  local slot=$1 n=$2
  python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path
p = Path("$ART/keeper_state.json")
st = json.loads(p.read_text())
sl = st.setdefault("slots", {}).setdefault("$slot", {})
prev = sl.get("last_json")
sl["last_json"] = int("$n")
sl["last_json_check"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
if prev is not None and int(prev) == int("$n"):
    sl.setdefault("stall_since", sl.get("stall_since") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
else:
    sl.pop("stall_since", None)
p.write_text(json.dumps(st, indent=2))
PY
}

keeper_one_pass() {
  load_art
  [[ -f "$ART/slots.tsv" ]] || { echo "no fleet run" >&2; exit 1; }
  local now slot name st tail json_n blocked ended down_for stall_for since_block
  now=$(date +%s)
  while IFS=$'\t' read -r slot port; do
    [[ -z "$slot" ]] && continue
    name="$(vm_name "$slot")"
    st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --project="$PROJECT" --format='value(status)' 2>/dev/null || echo MISSING)"
    if [[ "$st" != RUNNING ]]; then
      keeper_mark_down "$slot"
      down_for=$(keeper_secs_since "$slot" down_since)
      if [[ "$down_for" -ge "$KEEPER_DOWN_SEC" ]]; then
        recreate_slot "$slot" "down_${down_for}s"
      fi
      continue
    fi
    keeper_clear_down "$slot"
    remote='for f in /opt/ph/reuse/run_*.log; do [ -f "$f" ] || continue; tail -5 "$f"; done | tail -8
n=$(find /opt/ph/reuse/out -name "*.json" ! -name hb.json 2>/dev/null | wc -l)
alive=$(pgrep -cf "python.*ph_batch" || true)
echo JSON_COUNT=$n
echo BATCH_ALIVE=$alive'
    tail="$("${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet </dev/null --command="$remote" 2>/dev/null)" || tail=""
    json_n=$(echo "$tail" | sed -n 's/^JSON_COUNT=//p'); json_n=${json_n:-0}
    batch_alive=$(echo "$tail" | sed -n 's/^BATCH_ALIVE=//p'); batch_alive=${batch_alive:-0}
    keeper_note_json "$slot" "$json_n"
    blocked=0
    echo "$tail" | grep -qiE 'stopped_on_block|BLOCK HTTP 403|challenge not cleared' && blocked=1
    ended=0
  if [[ "$batch_alive" -eq 0 ]]; then
      "${GC[@]}" storage cat "${VM_GCS}/status/${name}.supervisor.jsonl" 2>/dev/null | tail -3 | grep -q supervisor_run_end && ended=1
    fi
    stall_for=$(keeper_secs_since "$slot" stall_since)
    if [[ "$stall_for" -ge "$KEEPER_STALL_SEC" ]]; then
      recreate_slot "$slot" "stall_${stall_for}s"
      continue
    fi
    if [[ "$blocked" -eq 1 || "$ended" -eq 1 ]]; then
      since_block=$(keeper_secs_since "$slot" last_recreate)
      # Mark first sighting of block so cooldown can elapse before recreate.
      if [[ "$blocked" -eq 1 ]]; then
        python3 - <<PY 2>/dev/null || true
import json
from datetime import datetime, timezone
from pathlib import Path
p = Path("$ART/keeper_state.json")
st = json.loads(p.read_text())
sl = st.setdefault("slots", {}).setdefault("$slot", {})
sl.setdefault("block_since", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
p.write_text(json.dumps(st, indent=2))
PY
      fi
      block_wait=$(keeper_secs_since "$slot" block_since)
      [[ "$block_wait" -eq 0 ]] && block_wait=$KEEPER_BLOCK_COOLDOWN_SEC
      if [[ "$blocked" -eq 1 && "$block_wait" -ge "$KEEPER_BLOCK_COOLDOWN_SEC" ]] || \
         [[ "$ended" -eq 1 && "$since_block" -ge "$KEEPER_BLOCK_COOLDOWN_SEC" ]]; then
        recreate_slot "$slot" "block_or_end"
        python3 - <<PY 2>/dev/null || true
import json
from pathlib import Path
st = json.loads(Path("$ART/keeper_state.json").read_text())
st.setdefault("slots", {}).setdefault("$slot", {}).pop("block_since", None)
Path("$ART/keeper_state.json").write_text(json.dumps(st, indent=2))
PY
      fi
    fi
  done <"$ART/slots.tsv"
}

cmd_keeper() {
  load_art
  local loop=0
  [[ "${1:-}" == --loop ]] && loop=1
  while :; do
    keeper_one_pass
    [[ "$loop" -eq 0 ]] && break
    sleep 60
  done
}

sample_slot() {
  local slot=$1 ts=$2
  local name port
  name="$(vm_name "$slot")"
  port="$(slot_field "$slot" 2)"
  local st
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --project="$PROJECT" --format='value(status)' 2>/dev/null || echo MISSING)"
  if [[ "$st" != RUNNING ]]; then
    echo -e "${ts}\t${slot}\t${name}\t${st}\t-\t-\t-\t-\tmissing"
    return
  fi
  remote='n=$(find /opt/ph/reuse/out -name "*.json" ! -name "hb.json" 2>/dev/null | wc -l)
t0=$(python3 -c "
import json
from pathlib import Path
p=Path(\"/opt/ph/reuse/setup_timing.jsonl\")
fp=None
for ln in p.read_text().splitlines() if p.exists() else []:
    try: j=json.loads(ln)
    except: continue
    if j.get(\"event\")==\"first_pull\": fp=j.get(\"utc\")
if fp:
    from datetime import datetime,timezone
    t=datetime.fromisoformat(fp.replace(\"Z\",\"+00:00\"))
    print(int((datetime.now(timezone.utc)-t).total_seconds()))
else:
    import os,time
    print(max(60,int(time.time()-os.path.getmtime(\"/opt/ph/reuse/supervisor.log\"))))
")
ppm=$(python3 -c "print(round($n*60.0/max(60,int($t0)),4))")
c403=0
for f in /opt/ph/reuse/run_*.log; do [ -f "$f" ] || continue; c403=$((c403+$(grep -cE "stopped_on_block|BLOCK HTTP 403" "$f" || true))); done
gen=$(grep -o "r[0-9]*" /opt/ph/reuse/last_token 2>/dev/null | tr -d r || echo 0)
echo "$n $ppm $c403 ${gen:-0}"'
  local line
  line="$("${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet </dev/null --command="$remote" 2>/dev/null)" || line="- - - -"
  read -r n ppm c403 gen <<<"$line" || true
  gen="${gen:-$(python3 -c "import json;print(json.load(open('$ART/keeper_state.json'))['slots'].get('$slot',{}).get('gen',0))" 2>/dev/null || echo 0)}"
  echo -e "${ts}\t${slot}\t${name}\t${st}\t${n:--}\t${ppm:--}\t${c403:--}\t${gen}\tport=${port}"
}

cmd_monitor() {
  load_art
  local loop=0
  [[ "${1:-}" == --loop ]] && loop=1
  local end=$(( $(date +%s) + DURATION_SEC ))
  while :; do
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    while IFS=$'\t' read -r slot _; do
      [[ -z "$slot" ]] && continue
      sample_slot "$slot" "$ts" | tee -a "$ART/samples.tsv"
    done <"$ART/slots.tsv"
    [[ "$loop" -eq 0 ]] && break
    [[ $(date +%s) -ge $end ]] && break
    sleep "$INTERVAL_SEC"
  done
}

cmd_summary() {
  load_art
  python3 - <<'PY' "$ART/samples.tsv" "$ART/started_at.txt"
import sys
from pathlib import Path
from datetime import datetime, timezone


def _f(x):
    try:
        float(x)
        return True
    except Exception:
        return False


samples, started = Path(sys.argv[1]), Path(sys.argv[2])
lines = samples.read_text().splitlines() if samples.exists() else []
rows = [ln.split("\t") for ln in lines[1:] if ln.strip()]
by_slot = {}
for r in rows:
    if len(r) < 7:
        continue
    by_slot.setdefault(r[1], []).append(r)
print("# Fleet summary — complete profiles (out/*.json); ppm from first_pull on VM")
print(f"started_at: {started.read_text().strip() if started.exists() else '?'}")
for slot, rs in sorted(by_slot.items()):
    nums = [int(r[4]) for r in rs if r[4].isdigit()]
    ppms = [float(r[5]) for r in rs if _f(r[5])]
    print(f"slot {slot}: last_json={nums[-1] if nums else 0} mean_sample_ppm={sum(ppms)/len(ppms) if ppms else 0:.4f} samples={len(rs)}")
last_by = {r[1]: r for r in rows if len(r) > 5}
fleet_json = sum(int(last_by[s][4]) for s in last_by if last_by[s][4].isdigit())
fleet_ppm = sum(float(last_by[s][5]) for s in last_by if _f(last_by[s][5]))
t0s = started.read_text().strip() if started.exists() else ""
if t0s:
    t0 = datetime.fromisoformat(t0s.replace("Z", "+00:00"))
    wall = (datetime.now(timezone.utc) - t0).total_seconds()
    wall_ppm = fleet_json * 60.0 / max(60, wall)
    print(f"\nFLEET json_sum={fleet_json} inst_ppm_sum={fleet_ppm:.4f} wall_ppm={wall_ppm:.4f} wall_min={wall/60:.1f}")
PY
}

cmd_down() {
  load_art
  while IFS=$'\t' read -r slot port; do
    [[ -z "$slot" ]] && continue
    name="$(vm_name "$slot")"
    "${GC[@]}" compute instances delete "$name" --zone="$ZONE" --project="$PROJECT" --quiet 2>/dev/null || true
    "${GC[@]}" storage rm "${PORT_PREFIX}/port.${port}" 2>/dev/null || true
  done <"$ART/slots.tsv"
}

cmd_patch_all() {
  load_art
  while IFS=$'\t' read -r slot _; do
    apply_patches_remote "$(vm_name "$slot")"
  done <"$ART/slots.tsv"
}

case "${1:-}" in
  up) shift; cmd_up "$@" ;;
  keeper) shift; cmd_keeper "$@" ;;
  monitor) shift; cmd_monitor "$@" ;;
  summary) cmd_summary ;;
  down) cmd_down ;;
  patch-all) cmd_patch_all ;;
  *) echo "usage: $0 up|keeper|monitor|summary|down|patch-all" >&2; exit 1 ;;
esac
