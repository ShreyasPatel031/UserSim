#!/usr/bin/env bash
# One VM × IPRoyal ISP: climb throughput ladder until blocks; find max steady complete/min.
#
#   export PACE_PROXY_FILE=/path/to/secrets/iproyal.purl
#   export PACE_FLEET_GO_TOKEN=pdeep:fleet-20261108t082000z   # optional; default fleet token
# Uses ONE existing fleet feeder (pace-feeder template): only proxy-url + strategy change.
#   export PACE_FLEET_RUN_ID=20261108t082000z
#   export PACE_PROXY_FILE=.../secrets/iproyal.purl
#   export PACE_TEMPLATE=pace-feeder-e2-standard-2   # optional, recommended
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
FLEET_RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
FLEET_RUN_ID="${FLEET_RUN_ID,,}"
LAB_RUN="${PACE_IPROYAL_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
LAB_RUN="${LAB_RUN,,}"
ART="${ROOT}/results/ph_iproyal_limit/${LAB_RUN}"
FLEET_ART="${ROOT}/results/ph_fleet_full/${FLEET_RUN_ID}"
PROXY_FILE="${PACE_PROXY_FILE:-$ROOT/secrets/iproyal.purl}"
VM_GCS="${PACE_VM_GCS:-gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"
OVERLAY_GCS="${VM_GCS}/_code/overlays"
TEMPLATE="${PACE_TEMPLATE:-pace-feeder-e2-standard-2}"
FLEET_SLOT="${FLEET_LIMIT_SLOT:-}"
VM_NAME=""
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

resolve_slot() {
  if [[ -n "$FLEET_SLOT" ]]; then echo "$FLEET_SLOT"; return; fi
  awk -F'\t' 'NF>=1 && $1+0==$1 {print $1; exit}' "$FLEET_ART/slots.tsv" 2>/dev/null || true
}

cmd_up() {
  [[ -f "$PROXY_FILE" ]] || { echo "missing PACE_PROXY_FILE=$PROXY_FILE" >&2; exit 1; }
  mkdir -p "$ART" "$FLEET_ART"
  touch "$FLEET_ART/slots.tsv"
  echo "$LAB_RUN" >"${ROOT}/results/ph_iproyal_limit/latest_run.txt"
  echo "$FLEET_RUN_ID" >"${ROOT}/results/ph_fleet_full/latest_run.txt"
  write_boot_env
  cp -f "$ART/pace.env" "$FLEET_ART/pace.env" 2>/dev/null || write_boot_env && cp "$ART/pace.env" "$FLEET_ART/pace.env"
  upload_overlays
  local start="${1:-L0_ultra}"
  envfile="$(merge_env "$start")"
  echo "$start" >"$ART/current_level.txt"
  export PACE_PROXY_FILE="$PROXY_FILE" PACE_TEMPLATE="$TEMPLATE" PACE_FLEET_RUN_ID="$FLEET_RUN_ID"
  export PH_FLEET_STRATEGY="$envfile"
  FLEET_MIN_VMS=0 FLEET_MAX_VMS=1 bash "$ROOT/scripts/vm/ph_fleet_autoscale.sh" scale-to 1
  FLEET_SLOT="$(resolve_slot)"
  [[ -n "$FLEET_SLOT" ]] || { echo "no fleet slot after scale-to 1" >&2; exit 1; }
  echo "$FLEET_SLOT" >"$ART/fleet_slot.txt"
  VM_NAME="feeder-fleet-${FLEET_RUN_ID}-${FLEET_SLOT}"
  ONLY_SLOTS="$FLEET_SLOT" PH_FLEET_STRATEGY_ENV="$envfile" bash "$ROOT/scripts/vm/ph_fleet_roll_patches.sh" | tail -3
  date -u +%Y-%m-%dT%H:%M:%SZ >"$ART/started_at.txt"
  echo "# ts level est_complete_ppm est_attempt_ppm blocks_15m browser_fail_15m phsuper note" >"$ART/samples.tsv"
  echo "# level verdict mean_complete_ppm max_complete_ppm blocks_15m" >"$ART/ladder.tsv"
  echo "fleet=$FLEET_RUN_ID slot=$FLEET_SLOT vm=$VM_NAME level=$start art=$ART"
}

cmd_apply() {
  local level="${1:?level e.g. L3_mid}"
  art_dir
  local envfile
  envfile="$(merge_env "$level")"
  echo "$level" >"$ART/current_level.txt"
  export PACE_PROXY_FILE="$PROXY_FILE" PACE_FLEET_RUN_ID="$FLEET_RUN_ID"
  "${GC[@]}" compute instances add-metadata "$VM_NAME" --zone="$ZONE" \
    --metadata-from-file="proxy-url=$PROXY_FILE,ph-strategy-env=$envfile" >/dev/null
  ONLY_SLOTS="$FLEET_SLOT" PH_FLEET_STRATEGY_ENV="$envfile" bash "$ROOT/scripts/vm/ph_fleet_roll_patches.sh" | tail -3
  echo "applied $level on $VM_NAME"
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
    rc=j.get("rc")
    if ev in ("saved","uploaded","pfull_saved") and (rc==0 or rc is None and "pfull" in (j.get("note") or "")): comp+=1
    if ev in ("saved","uploaded","pfull_saved") or (ev=="saved" and rc in (0,2)): att+=1
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
  export PACE_FLEET_RUN_ID="$FLEET_RUN_ID"
  FLEET_MIN_VMS=0 bash "$ROOT/scripts/vm/ph_fleet_autoscale.sh" scale-to 0 2>/dev/null || true
  echo "fleet scale-to 0 (was slot $FLEET_SLOT)"
}

art_dir() {
  if [[ -f "${ROOT}/results/ph_iproyal_limit/latest_run.txt" ]]; then
    LAB_RUN="$(cat "${ROOT}/results/ph_iproyal_limit/latest_run.txt")"
    ART="${ROOT}/results/ph_iproyal_limit/${LAB_RUN}"
  fi
  FLEET_RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
  FLEET_ART="${ROOT}/results/ph_fleet_full/${FLEET_RUN_ID,,}"
  FLEET_SLOT="${FLEET_SLOT:-$(cat "$ART/fleet_slot.txt" 2>/dev/null || resolve_slot)}"
  VM_NAME="feeder-fleet-${FLEET_RUN_ID}-${FLEET_SLOT}"
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
