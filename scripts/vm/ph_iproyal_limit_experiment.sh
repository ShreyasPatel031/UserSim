#!/usr/bin/env bash
# One VM × IPRoyal ISP: climb throughput ladder until blocks; find max steady complete/min.
#
#   export PACE_PROXY_FILE=/path/to/secrets/iproyal.purl
#   export PACE_FLEET_GO_TOKEN=pdeep:fleet-20261108t082000z   # optional; default fleet token
#   ./scripts/vm/ph_iproyal_limit_experiment.sh up
#   ./scripts/vm/ph_iproyal_limit_experiment.sh ladder --minutes 25
#   ./scripts/vm/ph_iproyal_limit_experiment.sh sample
#   ./scripts/vm/ph_iproyal_limit_experiment.sh apply L3_mid
#   ./scripts/vm/ph_iproyal_limit_experiment.sh summary
#   ./scripts/vm/ph_iproyal_limit_experiment.sh down
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT="${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:-}}"
ZONE="${PACE_ZONE:?export PACE_ZONE}"
[[ -n "$PROJECT" ]] || { echo "set GCP_PROJECT" >&2; exit 1; }
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
BUCKET="${MVP_GCS_BUCKET:?export MVP_GCS_BUCKET}"
RUN_ID="${PACE_IPROYAL_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_ID="${RUN_ID,,}"
ART="${ROOT}/results/ph_iproyal_limit/${RUN_ID}"
PROXY_FILE="${PACE_PROXY_FILE:-$ROOT/secrets/iproyal.purl}"
VM_GCS="${PACE_VM_GCS:-gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"
OVERLAY_GCS="${VM_GCS}/_code/overlays"
PORT_PREFIX="${PACE_PORT_REGISTRY_PREFIX:-${VM_GCS}/_ports}"
GO_TOKEN="${PACE_FLEET_GO_TOKEN:-pdeep:fleet-20261108t082000z}"
BOOK_PORT=10055
COMMON_META="pkg-name=bsit_full17.tgz;pkg-md5=Ku9PrVAfo8f+uDrIVfW8Bg==;k-levels=1,1;pace-state=0 600 0"
VM_NAME="feeder-iproyal-${RUN_ID}-1"
LADDER=(L0_ultra L1_polite L2_modest L3_mid L4_fleet80 L5_fleet120 L6_fleet160 L7_ceiling)
STEP_MIN="${LADDER_MINUTES:-25}"
WARMUP_SEC="${LADDER_WARMUP_SEC:-300}"
BLOCK_FAIL_STREAK="${LADDER_BLOCK_STREAK:-2}"

merge_env() {
  local level=$1
  local f="$ROOT/scripts/vm/ph_strategies/iproyal/${level}.env"
  [[ -f "$f" ]] || { echo "unknown level $level" >&2; exit 1; }
  local out="$ART/strategy_${level}.env"
  mkdir -p "$ART"
  { cat "$ROOT/scripts/vm/ph_strategies/iproyal/_base.env"; echo; cat "$f"; } >"$out"
  echo "$out"
}

upload_overlays() {
  local d="$ROOT/scripts/vm/reuse_overlays"
  "${GC[@]}" storage cp "$d"/*.py "$d/supervisor_strat.sh" "$d/ensure_geoip.sh" "$d/strategy_args.py" "${OVERLAY_GCS}/"
}

write_boot_env() {
  mkdir -p "$ART"
  cat >"$ART/pace.env" <<EOF
MVP_GCS_BUCKET=${BUCKET}
PACE_GCS_VM_ROOT=${VM_GCS}
PH_OVERLAYS_DIR=/opt/ph/overlays
PH_PROXY_FIXED_PORT=1
PH_PORTSCREEN_HOME_ONLY=1
PH_PORTSCREEN_MAX_TRY=1
EOF
}

cmd_up() {
  [[ -f "$PROXY_FILE" ]] || { echo "missing PACE_PROXY_FILE=$PROXY_FILE" >&2; exit 1; }
  mkdir -p "$ART"
  echo "$RUN_ID" >"${ROOT}/results/ph_iproyal_limit/latest_run.txt"
  write_boot_env
  upload_overlays
  local start="${1:-L0_ultra}"
  local envfile
  envfile="$(merge_env "$start")"
  echo "$start" >"$ART/current_level.txt"
  printf '%s\n' "$VM_NAME" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"${PORT_PREFIX}/port.${BOOK_PORT}" 2>/dev/null || \
    echo "$VM_NAME" | "${GC[@]}" storage cp - "${PORT_PREFIX}/port.${BOOK_PORT}"
  meta="^;^proxy-port=${BOOK_PORT};${COMMON_META};iproyal-level=${start}"
  echo "==> create $VM_NAME level=$start"
  "${GC[@]}" compute instances create "$VM_NAME" \
    --project="$PROJECT" --zone="$ZONE" \
    --machine-type=e2-standard-2 \
    --network=main-vpc --subnet=primary-subnet \
    --image-family=pace-feeder --image-project="$PROJECT" --boot-disk-size=20GB \
    --service-account="$SA" --scopes=cloud-platform \
    --tags=allow-iap-ssh \
    --metadata-from-file "proxy-url=$PROXY_FILE,ph-strategy-env=$envfile,pace-boot-env=$ART/pace.env,startup-script=$ROOT/pace_startup.sh" \
    --metadata "$meta" \
    || "${GC[@]}" compute instances create "$VM_NAME" \
      --project="$PROJECT" --zone="$ZONE" \
      --machine-type=e2-standard-2 \
      --network=main-vpc --subnet=primary-subnet \
      --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=20GB \
      --service-account="$SA" --scopes=cloud-platform \
      --tags=allow-iap-ssh \
      --metadata-from-file "proxy-url=$PROXY_FILE,ph-strategy-env=$envfile,pace-boot-env=$ART/pace.env,startup-script=$ROOT/pace_startup.sh" \
      --metadata "$meta"
  echo "$GO_TOKEN" | "${GC[@]}" storage cp - "${VM_GCS}/GO.${VM_NAME}"
  date -u +%Y-%m-%dT%H:%M:%SZ >"$ART/started_at.txt"
  echo "# ts level est_complete_ppm est_attempt_ppm blocks_15m browser_fail_15m phsuper note" >"$ART/samples.tsv"
  echo "# level verdict mean_complete_ppm max_complete_ppm blocks_15m" >"$ART/ladder.tsv"
  echo "RUN_ID=$RUN_ID vm=$VM_NAME GO=$GO_TOKEN art=$ART"
}

roll_remote() {
  local envfile=$1
  "${GC[@]}" compute instances add-metadata "$VM_NAME" --zone="$ZONE" \
    --metadata-from-file="ph-strategy-env=$envfile" >/dev/null
  "${GC[@]}" compute ssh "$VM_NAME" --zone="$ZONE" --tunnel-through-iap --quiet </dev/null --command='set -e
B=$(grep -E "^PACE_GCS_VM_ROOT=" /opt/ph/pace.env | cut -d= -f2-)
gcloud storage cp -q "$B/_code/overlays/supervisor_strat.sh" "$B/_code/overlays/"*.py /opt/ph/overlays/ 2>/dev/null || true
sudo cp -f /opt/ph/overlays/*.py /opt/ph/overlays/ 2>/dev/null || true
sudo install -m 755 /opt/ph/overlays/supervisor_strat.sh /opt/ph/overlays/supervisor_strat.sh 2>/dev/null || true
sudo cp -f /tmp/strat.env /opt/ph/strategy.env 2>/dev/null || true
curl -sf -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/instance/attributes/ph-strategy-env | sudo tee /opt/ph/strategy.env >/dev/null
sudo rm -f /opt/ph/reuse/KICK /opt/ph/reuse/port_override /opt/ph/reuse/cf_cooldown_until 2>/dev/null || true
sudo systemctl stop phsuper 2>/dev/null || true
sudo pkill -f "[p]deep.py|[p]h_batch.py" 2>/dev/null || true
EA=""; [[ -f /opt/ph/pace.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/pace.env"; [[ -f /opt/ph/strategy.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/strategy.env"
sudo systemd-run --unit=phsuper --collect -p WorkingDirectory=/opt/ph/reuse $EA /bin/bash -c "bash /opt/ph/overlays/supervisor_strat.sh >> /opt/ph/reuse/supervisor.log 2>&1" >/dev/null 2>&1
sleep 2; systemctl is-active phsuper
echo ROLL_OK'
}

cmd_apply() {
  local level="${1:?level e.g. L3_mid}"
  art_dir
  local envfile
  envfile="$(merge_env "$level")"
  echo "$level" >"$ART/current_level.txt"
  roll_remote "$envfile"
  echo "applied $level"
}

sample_remote() {
  "${GC[@]}" compute ssh "$VM_NAME" --zone="$ZONE" --tunnel-through-iap --quiet </dev/null --command='python3 <<PY
import json, time, subprocess, glob
from datetime import datetime, timezone
now=time.time()
win=900
status=glob.glob("/opt/ph/reuse/status_*.jsonl")
lines=[]
for p in status:
    try: lines.extend(open(p).read().splitlines()[-400:])
    except Exception: pass
def ts(s):
    try: return datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
    except Exception: return 0
comp=att=blocks=bf=0
for ln in lines:
    try: j=json.loads(ln)
    except Exception: continue
    t=ts(j.get("utc") or "")
    if now-t>win: continue
    ev=j.get("event") or ""
    if ev in ("saved","uploaded") and j.get("rc")==0: comp+=1
    if ev in ("saved","uploaded"): att+=1
    if "block" in ev or ev=="stopped_on_block": blocks+=1
    if ev=="browser_open_failed": bf+=1
ppm_c=round(comp*60/win,3) if win else 0
ppm_a=round(att*60/win,3) if win else 0
ph= subprocess.getoutput("systemctl is-active phsuper 2>/dev/null") or "?"
print(json.dumps({"complete_ppm":ppm_c,"attempt_ppm":ppm_a,"blocks_15m":blocks,"browser_fail_15m":bf,"phsuper":ph}))
PY' 2>/dev/null || echo '{"complete_ppm":0,"attempt_ppm":0,"blocks_15m":0,"browser_fail_15m":0,"phsuper":"ssh_fail"}'
}

cmd_sample() {
  art_dir
  local level ts j
  level="$(cat "$ART/current_level.txt" 2>/dev/null || echo "?")"
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  j="$(sample_remote)"
  python3 - <<PY "$ts" "$level" "$j" "$ART/samples.tsv"
import json, sys
from pathlib import Path
ts, level, j, out = sys.argv[1:5]
m=json.loads(j)
note=""
if m.get("browser_fail_15m",0)>=3: note="browser_fail"
if m.get("blocks_15m",0)>=2: note="blocks"
row="\t".join([ts, level, str(m.get("complete_ppm")), str(m.get("attempt_ppm")),
               str(m.get("blocks_15m")), str(m.get("browser_fail_15m")), str(m.get("phsuper")), note])
Path(out).open("a").write(row+"\n")
print(row)
PY
}

cmd_ladder() {
  local from="${1:-L0_ultra}"
  art_dir
  local seen=0
  for lv in "${LADDER[@]}"; do
    [[ "$seen" -eq 0 && "$lv" != "$from" ]] && continue
    seen=1
    echo "===== LADDER $lv ====="
    cmd_apply "$lv"
    echo "warmup ${WARMUP_SEC}s..."
    sleep "$WARMUP_SEC"
    local fail=0 sum_c=0 n=0 max_c=0 blocks=0
    local steps=$(( STEP_MIN * 60 / 300 ))
    [[ "$steps" -lt 1 ]] && steps=1
    for ((s=0;s<steps;s++)); do
      sleep 300
      line="$(cmd_sample)"
      c="$(echo "$line" | cut -f3)"
      b="$(echo "$line" | cut -f5)"
      bf="$(echo "$line" | cut -f6)"
      python3 -c "c=float('$c' or 0); exit(0 if c>0 or int('$bf')<2 else 1)" 2>/dev/null || fail=$((fail+1))
      [[ "$bf" -ge 4 || "$b" -ge 3 ]] && fail=$((fail+1))
      sum_c="$(python3 -c "print(float('$sum_c')+float('$c' or 0))")"
      max_c="$(python3 -c "print(max(float('$max_c'),float('$c' or 0)))")"
      n=$((n+1))
      blocks=$((blocks + b))
    done
    mean_c="$(python3 -c "print(round(float('$sum_c')/max(1,$n),3))")"
    verdict=ok
    [[ "$fail" -ge "$BLOCK_FAIL_STREAK" ]] && verdict=block
    echo -e "${lv}\t${verdict}\t${mean_c}\t${max_c}\t${blocks}" >>"$ART/ladder.tsv"
    echo "level $lv verdict=$verdict mean_complete_ppm=$mean_c max=$max_c"
    [[ "$verdict" == block ]] && { echo "Stopping ladder at $lv (prior level is best steady)"; break; }
  done
  cmd_summary
}

cmd_summary() {
  art_dir
  echo "=== ladder.tsv ==="
  column -t "$ART/ladder.tsv" 2>/dev/null || cat "$ART/ladder.tsv"
  python3 - <<PY
from pathlib import Path
p=Path("$ART/ladder.tsv")
rows=[l.split("\t") for l in p.read_text().splitlines() if l and not l.startswith("#")]
best=None
for r in rows:
    if len(r)<3: continue
    if r[1]=="ok":
        best=r[0]
print("Best steady level (last OK):", best or "none yet")
PY
}

cmd_down() {
  art_dir
  "${GC[@]}" compute instances delete "$VM_NAME" --zone="$ZONE" --quiet 2>/dev/null || true
  "${GC[@]}" storage rm "${PORT_PREFIX}/port.${BOOK_PORT}" 2>/dev/null || true
  echo "deleted $VM_NAME"
}

art_dir() {
  if [[ -f "${ROOT}/results/ph_iproyal_limit/latest_run.txt" ]]; then
    RUN_ID="$(cat "${ROOT}/results/ph_iproyal_limit/latest_run.txt")"
    ART="${ROOT}/results/ph_iproyal_limit/${RUN_ID}"
    VM_NAME="feeder-iproyal-${RUN_ID}-1"
  fi
}

case "${1:-}" in
  up) shift; cmd_up "${1:-L0_ultra}" ;;
  apply) shift; art_dir; cmd_apply "$@" ;;
  sample) art_dir; cmd_sample ;;
  ladder) shift; cmd_ladder "${1:-L0_ultra}" ;;
  summary) art_dir; cmd_summary ;;
  down) cmd_down ;;
  *)
    echo "usage: $0 up [L0_ultra]|apply LEVEL|sample|ladder [from_level]|summary|down" >&2
    exit 1 ;;
esac
