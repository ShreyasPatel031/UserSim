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
LADDER=(Lm1_serial L0_ultra L1_polite L2_modest L3_mid L4_fleet80 L5_fleet120 L6_fleet160 L7_ceiling)
STEP_MIN="${LADDER_MINUTES:-12}"
WARMUP_SEC="${LADDER_WARMUP_SEC:-240}"
SAMPLE_WIN_SEC="${LADDER_SAMPLE_WIN_SEC:-300}"
BLOCK_FAIL_STREAK="${LADDER_BLOCK_STREAK:-3}"
STEADY_MIN_PPM="${LADDER_STEADY_MIN_PPM:-0.35}"

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
  echo "# ts	level	complete_ppm	attempt_ppm	gql429_5m	walls_5m	phsuper	pdeep_k	note" >"$ART/samples.tsv"
  echo "# level	verdict	mean_complete_ppm	max_complete_ppm	mean_gql429_5m	walls_5m	pdeep_k" >"$ART/ladder.tsv"
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
  local win="${SAMPLE_WIN_SEC}"
  "${GC[@]}" compute ssh "$VM_NAME" --zone="$ZONE" --tunnel-through-iap --quiet </dev/null --command="python3 <<'PY'
import json, socket, subprocess, time
from datetime import datetime, timezone
W=${win}
now=time.time()
host=socket.gethostname()
path=f'/opt/ph/reuse/status_{host}.jsonl'
def ts(u):
    try: return datetime.fromisoformat(u.replace('Z','+00:00')).timestamp()
    except Exception: return None
rows=open(path).read().splitlines() if __import__('os').path.isfile(path) else []
nc=nr=gql429=walls=0
start_k=start_t=None
for ln in rows:
    try: j=json.loads(ln)
    except Exception: continue
    ev=j.get('event'); rc=j.get('rc')
    if ev=='start':
        start_k=(j.get('workers'), j.get('tabs_per_worker'), j.get('port'))
        start_t=j.get('utc')
    t=ts(j.get('utc') or '')
    if not t or now-t>W: continue
    if j.get('handle') and rc is not None:
        ok = rc==0 and ev!='incomplete_skip_upload' and str(j.get('method') or '').startswith('pfull')
        if ok: nc+=1
        else: nr+=1
        if rc==3 and '429' in (j.get('detail') or ''): gql429+=1
    elif ev in ('stopped_on_block','browser_open_failed') or (ev=='supervisor_run_end' and rc==3):
        walls+=1
m=max(W/60.0, 1/60.0)
out={'complete_ppm':round(nc/m,3),'attempt_ppm':round((nc+nr)/m,3),'gql429_5m':gql429,'walls_5m':walls,
     'pdeep_k':start_k,'pdeep_started':start_t,'phsuper':subprocess.getoutput('systemctl is-active phsuper 2>/dev/null') or '?'}
print(json.dumps(out))
PY" 2>/dev/null || echo '{"complete_ppm":0,"attempt_ppm":0,"gql429_5m":0,"walls_5m":0,"phsuper":"ssh_fail"}'
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
if m.get("walls_5m",0)>=3: note="walls"
if m.get("gql429_5m",0)>=4: note="gql429"
if float(m.get("complete_ppm") or 0)<0.05 and float(m.get("attempt_ppm") or 0)>0.2: note=(note+" starved").strip()
row="\t".join([ts, level, str(m.get("complete_ppm")), str(m.get("attempt_ppm")),
               str(m.get("gql429_5m")), str(m.get("walls_5m")), str(m.get("phsuper")),
               str(m.get("pdeep_k")), note])
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
    local fail=0 sum_c=0 sum_g=0 n=0 max_c=0 walls=0 ksnap=""
    local steps=$(( STEP_MIN * 60 / 300 ))
    [[ "$steps" -lt 1 ]] && steps=1
    for ((s=0;s<steps;s++)); do
      sleep 300
      line="$(cmd_sample)"
      c="$(echo "$line" | cut -f3)"
      g="$(echo "$line" | cut -f5)"
      w="$(echo "$line" | cut -f6)"
      ksnap="$(echo "$line" | cut -f8)"
      python3 -c "import sys; c=float('$c' or 0); g=int('$g' or 0); w=int('$w' or 0); steady=float('$STEADY_MIN_PPM');
exit(1 if c<steady and g>=3 else 0)" 2>/dev/null || fail=$((fail+1))
      [[ "$w" -ge 4 ]] && fail=$((fail+1))
      sum_c="$(python3 -c "print(float('$sum_c')+float('$c' or 0))")"
      sum_g="$(python3 -c "print(float('$sum_g')+float('$g' or 0))")"
      max_c="$(python3 -c "print(max(float('$max_c'),float('$c' or 0)))")"
      n=$((n+1))
      walls=$((walls + w))
    done
    mean_c="$(python3 -c "print(round(float('$sum_c')/max(1,$n),3))")"
    mean_g="$(python3 -c "print(round(float('$sum_g')/max(1,$n),2))")"
    verdict=ok
    [[ "$fail" -ge "$BLOCK_FAIL_STREAK" ]] && verdict=block
    python3 -c "import sys; mc=float('$mean_c'); steady=float('$STEADY_MIN_PPM'); sys.exit(1 if mc<steady else 0)" 2>/dev/null || verdict=block
    echo -e "${lv}\t${verdict}\t${mean_c}\t${max_c}\t${mean_g}\t${walls}\t${ksnap}" >>"$ART/ladder.tsv"
    echo "level $lv verdict=$verdict mean_complete_ppm=$mean_c max=$max_c mean_gql429_5m=$mean_g pdeep_k=$ksnap"
    [[ "$verdict" == block ]] && { echo "Stopping ladder at $lv (last OK level is max buy-safe concurrency)"; break; }
  done
  cmd_summary
  cmd_report
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

cmd_report() {
  art_dir
  local rep="$ART/purchase_decision.txt"
  python3 - <<PY >"$rep"
from pathlib import Path
art=Path("$ART")
lad=art/"ladder.tsv"
lines=[l.split("\t") for l in lad.read_text().splitlines() if l and not l.startswith("#")]
ok=[r for r in lines if len(r)>=4 and r[1]=="ok"]
best=ok[-1] if ok else None
def ips_for(rate, per_ip):
    if per_ip<=0: return "n/a"
    import math
    return {t: max(1, math.ceil(t/per_ip)) for t in (20, 30)}
print("IPRoyal single-IP ladder", art.name)
print("proxy: Spain ISP 213.220.25.150 (fixed port)")
print()
if not lines:
    print("No ladder data yet — run: ph_iproyal_limit_experiment.sh ladder")
else:
    print("Ladder results:")
    for r in lines:
        print(" ", "\t".join(r))
print()
if best:
    lvl, _, mean_c, max_c = best[0], best[1], float(best[2]), float(best[3])
    per=float(mean_c)
    print(f"Recommended per-IP concurrency: {lvl}")
    print(f"  mean complete/min (12m window): {mean_c}")
    print(f"  peak 5m sample complete/min:    {max_c}")
    if best[6:7]:
        print(f"  pdeep shape (K,TABS,port):      {best[6]}")
    for target in (20, 30):
        n=ips_for(target, per).get(target)
        print(f"  dedicated IPs (+1 VM each) for ~{target} complete/min fleet: ~{n}")
    print()
    print("Buy rule: 1 static ISP IP per feeder VM at the recommended level.")
    print("Do not stack multiple VMs on one IP — 429 budget is per egress.")
else:
    print("No OK level yet — stay at Lm1_serial until ladder finishes.")
print()
print("Artifacts:", art/"ladder.tsv", art/"samples.tsv")
PY
  echo "=== purchase_decision.txt ==="
  cat "$rep"
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
  ladder) shift; cmd_ladder "${1:-Lm1_serial}" ;;
  summary) art_dir; cmd_summary ;;
  report) art_dir; cmd_report ;;
  down) cmd_down ;;
  *)
    echo "usage: $0 up [Lm1_serial]|apply LEVEL|sample|ladder [from_level]|summary|report|down" >&2
    exit 1 ;;
esac
