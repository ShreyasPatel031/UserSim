#!/usr/bin/env bash
# Four-VM exploration: tab/ramp strategies on live queue, 4h default, 15m health samples.
#
#   ./scripts/vm/ph_tab_strategy_experiment.sh up --use-template --fetch-proxy-from feeder-phpeople-1
#   ./scripts/vm/ph_tab_strategy_experiment.sh monitor --loop
#   ./scripts/vm/ph_tab_strategy_experiment.sh summary
#   ./scripts/vm/ph_tab_strategy_experiment.sh down
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT="${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:-}}"
ZONE="${PACE_ZONE:?export PACE_ZONE}"
[[ -n "$PROJECT" ]] || { echo "set GCP_PROJECT" >&2; exit 1; }
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${PROJECT}.iam.gserviceaccount.com}"
if [[ -d /home/ubuntu/google-cloud-sdk/bin ]]; then
  export PATH="/home/ubuntu/google-cloud-sdk/bin:$PATH"
fi
GC=(gcloud --account="$SA")
BUCKET="${MVP_GCS_BUCKET:?export MVP_GCS_BUCKET}"
PORT_PREFIX="${PACE_PORT_REGISTRY_PREFIX:-gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm/_ports}"
DURATION_SEC="${DURATION_SEC:-14400}"
INTERVAL_SEC="${INTERVAL_SEC:-900}"
RUN_ID="${PACE_EXPERIMENT_RUN_ID:-${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}}"
RUN_ID="${RUN_ID,,}" # GCE names: lowercase only
ART="${ROOT}/results/ph_tab_experiment/${RUN_ID}"
PROXY_FILE="${PACE_PROXY_FILE:-$ROOT/.purl}"
NEVER_PORTS=(10001 10005 10006 10020)

STRATEGIES=(
  "a:${ROOT}/scripts/vm/ph_strategies/A_serial_polite.env"
  "b:${ROOT}/scripts/vm/ph_strategies/B_aimd_adaptive.env"
  "c:${ROOT}/scripts/vm/ph_strategies/C_burst_coast.env"
  "d:${ROOT}/scripts/vm/ph_strategies/D_req_budget.env"
)
COMMON_META="pkg-name=bsit_full17.tgz;pkg-md5=Ku9PrVAfo8f+uDrIVfW8Bg==;k-levels=1,1;pace-state=0 600 0"
TEMPLATE="${PACE_TEMPLATE:-pace-feeder-e2-standard-2}"
USE_TEMPLATE=0
VM_GCS="${PACE_VM_GCS:-gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"
OVERLAY_GCS="${VM_GCS}/_code/overlays"
GO_TOKEN="run:strat-${RUN_ID}"

upload_overlays() {
  local d="$ROOT/scripts/vm/reuse_overlays"
  [[ -f "$d/supervisor_strat.sh" ]] || { echo "missing overlays in $d" >&2; exit 1; }
  "${GC[@]}" storage cp "$d/supervisor_strat.sh" "$d/portscreen.py" "$d/strategy_args.py" "${OVERLAY_GCS}/"
  echo "Uploaded overlays -> ${OVERLAY_GCS}/"
}

write_boot_env() {
  cat >"$ART/pace.env" <<EOF
MVP_GCS_BUCKET=${BUCKET}
PACE_GCS_VM_ROOT=${VM_GCS}
PH_OVERLAYS_DIR=/opt/ph/overlays
EOF
}

write_go_tokens() {
  while IFS=$'\t' read -r sid _ _; do
    [[ -z "$sid" ]] && continue
    echo "$GO_TOKEN" | "${GC[@]}" storage cp - "${VM_GCS}/GO.$(vm_name "$sid")"
  done <"$ART/instances.tsv"
  echo "Wrote GO.* tokens ($GO_TOKEN)"
}

release_ports() {
  [[ -f "$ART/instances.tsv" ]] || return 0
  while IFS=$'\t' read -r sid port _; do
    [[ -z "$sid" || -z "$port" ]] && continue
    "${GC[@]}" storage rm "${PORT_PREFIX}/port.${port}" 2>/dev/null || true
  done <"$ART/instances.tsv"
}

art_dir() {
  if [[ -n "${PACE_EXPERIMENT_RUN_ID:-}" ]]; then
    RUN_ID="${PACE_EXPERIMENT_RUN_ID,,}"
  elif [[ -f "${ROOT}/results/ph_tab_experiment/latest_run.txt" ]]; then
    RUN_ID="$(cat "${ROOT}/results/ph_tab_experiment/latest_run.txt")"
  fi
  ART="${ROOT}/results/ph_tab_experiment/${RUN_ID}"
  GO_TOKEN="run:strat-${RUN_ID}"
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

next_port() {
  local taken p
  taken="$("${GC[@]}" storage ls "${PORT_PREFIX}/" 2>/dev/null | sed -n 's/.*port\.\([0-9]*\).*/\1/p' | sort -nu)"
  for p in $(seq 10000 20000); do
    printf '%s\n' "${NEVER_PORTS[@]}" | grep -qx "$p" && continue
    echo "$taken" | grep -qx "$p" && continue
    echo "$p"
    return 0
  done
  echo "no free sticky port in 10000-20000" >&2
  return 1
}

vm_name() { echo "feeder-strat-${RUN_ID}-${1}"; }

cmd_up() {
  local fetch_from=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --fetch-proxy-from) fetch_from=$2; shift 2 ;;
      --use-template) USE_TEMPLATE=1; shift ;;
      *) echo "unknown: $1" >&2; exit 1 ;;
    esac
  done
  [[ -n "$fetch_from" ]] && fetch_proxy "$fetch_from"
  [[ -f "$PROXY_FILE" ]] || { echo "missing $PROXY_FILE; use --fetch-proxy-from" >&2; exit 1; }
  mkdir -p "$ART"
  echo "$RUN_ID" >"${ROOT}/results/ph_tab_experiment/latest_run.txt"
  write_boot_env
  upload_overlays
  : >"$ART/instances.tsv"
  for spec in "${STRATEGIES[@]}"; do
    IFS=: read -r sid envfile <<<"$spec"
    [[ -f "$envfile" ]] || { echo "missing $envfile" >&2; exit 1; }
    name="$(vm_name "$sid")"
    port="$(next_port)"
    echo -e "${sid}\t${port}\t$(basename "$envfile")" >>"$ART/instances.tsv"
    echo "==> $name port=$port strategy=$sid"
    printf '%s %s strat-%s\n' "$name" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$sid" |
      "${GC[@]}" storage cp - "${PORT_PREFIX}/port.${port}"
    meta="^;^proxy-port=${port};${COMMON_META};strat-id=${sid}"
    # Always inject current startup + overlays boot env (template image may be stale).
    if [[ "$USE_TEMPLATE" -eq 1 ]]; then
      "${GC[@]}" compute instances create "$name" \
        --project="$PROJECT" --zone="$ZONE" \
        --source-instance-template="$TEMPLATE" \
        --metadata-from-file "proxy-url=$PROXY_FILE,ph-strategy-env=$envfile,pace-boot-env=$ART/pace.env,startup-script=$ROOT/pace_startup.sh" \
        --metadata "$meta"
    else
      "${GC[@]}" compute instances create "$name" \
        --project="$PROJECT" --zone="$ZONE" \
        --machine-type=e2-standard-2 \
        --network=main-vpc --subnet=primary-subnet \
        --image-family=pace-feeder --image-project="$PROJECT" --boot-disk-size=20GB \
        --service-account="$SA" --scopes=cloud-platform \
        --tags=allow-iap-ssh \
        --metadata-from-file "proxy-url=$PROXY_FILE,ph-strategy-env=$envfile,pace-boot-env=$ART/pace.env,startup-script=$ROOT/pace_startup.sh" \
        --metadata "$meta" \
        || "${GC[@]}" compute instances create "$name" \
          --project="$PROJECT" --zone="$ZONE" \
          --machine-type=e2-standard-2 \
          --network=main-vpc --subnet=primary-subnet \
          --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=20GB \
          --service-account="$SA" --scopes=cloud-platform \
          --tags=allow-iap-ssh \
          --metadata-from-file "proxy-url=$PROXY_FILE,ph-strategy-env=$envfile,pace-boot-env=$ART/pace.env,startup-script=$ROOT/pace_startup.sh" \
          --metadata "$meta"
    fi
  done
  write_go_tokens
  date -u +%Y-%m-%dT%H:%M:%SZ >"$ART/started_at.txt"
  echo "# ts strat vm status phsuper json_count est_ppm 403_hints runtime_port strategy_args" >"$ART/samples.tsv"
  echo "RUN_ID=$RUN_ID  artifacts=$ART  GO=$GO_TOKEN"
}

sample_one() {
  local sid=$1 name=$2 ts=$3
  local st line remote
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --project="$PROJECT" --format='value(status)' 2>/dev/null || echo MISSING)"
  if [[ "$st" != RUNNING ]]; then
    echo -e "${ts}\t${sid}\t${name}\t${st}\t-\t-\t-\t-\t-\t-"
    return
  fi
  remote='phsuper=$(systemctl is-active phsuper 2>/dev/null || echo unknown)
n=$(find /opt/ph/reuse/out -name "*.json" ! -name "hb.json" 2>/dev/null | wc -l)
start=$(stat -c %Y /opt/ph/reuse/supervisor.log 2>/dev/null || date +%s)
wall=$(( $(date +%s) - start )); [ "$wall" -lt 60 ] && wall=60
ppm=$(python3 -c "print(round($n*60.0/$wall,4))")
c403=0
for f in /opt/ph/reuse/run_*.log; do [ -f "$f" ] || continue; c403=$((c403+$(grep -cE "BLOCK|challenge not cleared" "$f" || true))); done
rport=$(grep -E "FINGERPRINT_(NEW|REUSED)" /opt/ph/reuse/run_*.log 2>/dev/null | tail -1 | grep -oE "port [0-9]+" | awk "{print \$2}")
[ -z "$rport" ] && rport=$(curl -sf -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/instance/attributes/proxy-port)
sargs=$(grep -E "^launch " /opt/ph/reuse/supervisor.log 2>/dev/null | tail -1 | sed -n "s/.*extra=\[\(.*\)\].*/\1/p" | tr " " _)
echo "$phsuper $n $ppm $c403 ${rport:-?} ${sargs:-?}"'
  # Redirect stdin so nested SSH cannot consume the caller's instances.tsv loop.
  line="$("${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet --command="$remote" </dev/null 2>/dev/null)" || line="- - - - - -"
  local phsuper count ppm c403 rport sargs
  read -r phsuper count ppm c403 rport sargs <<<"$line" || true
  echo -e "${ts}\t${sid}\t${name}\t${st}\t${phsuper:--}\t${count:--}\t${ppm:--}\t${c403:--}\t${rport:--}\t${sargs:--}"
}

cmd_monitor() {
  art_dir
  [[ -f "$ART/instances.tsv" ]] || { echo "no $ART/instances.tsv — run up first" >&2; exit 1; }
  local loop=0
  [[ "${1:-}" == --loop ]] && loop=1
  local end=$(( $(date +%s) + DURATION_SEC ))
  while :; do
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    while IFS=$'\t' read -r sid port _env; do
      [[ -z "$sid" ]] && continue
      sample_one "$sid" "feeder-strat-${RUN_ID}-${sid}" "$ts" | tee -a "$ART/samples.tsv" | tee -a "$ART/monitor.log"
    done <"$ART/instances.tsv"
    [[ "$loop" -eq 0 ]] && break
    [[ $(date +%s) -ge $end ]] && break
    sleep "$INTERVAL_SEC"
  done
}

cmd_summary() {
  art_dir
  python3 - <<'PY' "$ART"
import sys
from pathlib import Path
from collections import defaultdict

art = Path(sys.argv[1])
samples = art / "samples.tsv"
if not samples.exists():
    raise SystemExit(f"missing {samples}")
by = defaultdict(list)
last = {}
for line in samples.read_text().splitlines():
    if line.startswith("#") or not line.strip():
        continue
    parts = line.split("\t")
    if len(parts) < 7:
        continue
    sid, count, ppm = parts[1], parts[5], parts[6]
    try:
        by[sid].append(float(ppm))
        last[sid] = (count, ppm, parts[8] if len(parts) > 8 else "?", parts[9] if len(parts) > 9 else "?")
    except ValueError:
        pass
print("strategy\tmean_est_ppm\tn_samples\tlast_json\tlast_ppm\truntime_port\targs")
best = None
for sid in sorted(by):
    xs = by[sid]
    m = sum(xs) / len(xs) if xs else 0.0
    c, p, port, args = last.get(sid, ("?", "?", "?", "?"))
    print(f"{sid}\t{m:.4f}\t{len(xs)}\t{c}\t{p}\t{port}\t{args}")
    if best is None or m > best[1]:
        best = (sid, m)
if best:
    print(f"\nWINNER (mean est. people/min): {best[0]} @ {best[1]:.4f}")
PY
}

cmd_down() {
  art_dir
  [[ -f "$ART/instances.tsv" ]] || exit 0
  while IFS=$'\t' read -r sid _; do
    [[ -z "$sid" ]] && continue
    "${GC[@]}" compute instances delete "feeder-strat-${RUN_ID}-${sid}" --zone="$ZONE" --project="$PROJECT" --quiet 2>/dev/null || true
  done <"$ART/instances.tsv"
  release_ports
}

case "${1:-}" in
  up) shift; cmd_up "$@" ;;
  monitor) shift; cmd_monitor "$@" ;;
  summary) cmd_summary ;;
  down) cmd_down ;;
  upload-overlays) upload_overlays ;;
  *)
    sed -n '2,10p' "$0" | sed 's/^# //'
    exit 1
    ;;
esac
