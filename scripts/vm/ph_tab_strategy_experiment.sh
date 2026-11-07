#!/usr/bin/env bash
# Four-VM exploration: tab/ramp strategies on live queue, 4h default, 15m health samples.
#
#   export PACE_EXPERIMENT_RUN_ID=20261107T161500Z   # optional; pins artifact dir
#   ./scripts/vm/ph_tab_strategy_experiment.sh up --fetch-proxy-from feeder-phpeople-1
#   ./scripts/vm/ph_tab_strategy_experiment.sh monitor --loop   # 15m samples for DURATION_SEC
#   ./scripts/vm/ph_tab_strategy_experiment.sh summary
#   ./scripts/vm/ph_tab_strategy_experiment.sh down
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT="${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:-}}"
ZONE="${PACE_ZONE:?export PACE_ZONE}"
[[ -n "$PROJECT" ]] || { echo "set GCP_PROJECT" >&2; exit 1; }
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
PORT_PREFIX="${PACE_PORT_REGISTRY_PREFIX:-gs://${PACE_PORT_REGISTRY_BUCKET:-[REDACTED]}/usersim_sim/raw/ph_population/people_live/vm/_ports}"
DURATION_SEC="${DURATION_SEC:-14400}"
INTERVAL_SEC="${INTERVAL_SEC:-900}"
RUN_ID="${PACE_EXPERIMENT_RUN_ID:-${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}}"
ART="${ROOT}/results/ph_tab_experiment/${RUN_ID}"
PROXY_FILE="${PACE_PROXY_FILE:-$ROOT/.purl}"

STRATEGIES=(
  "A:8:1:30,8:60"
  "B:16:1:30,8:90,16:120"
  "C:32:1:30,8:90,16:120,32:150"
  "D:48:1:40,16:120,32:150,48:180"
)
COMMON_META="pkg-name=bsit_full17.tgz;pkg-md5=Ku9PrVAfo8f+uDrIVfW8Bg==;k-levels=1,1;pace-state=1 600 0"

art_dir() {
  if [[ -n "${PACE_EXPERIMENT_RUN_ID:-}" ]]; then
    RUN_ID="$PACE_EXPERIMENT_RUN_ID"
  elif [[ -f "${ROOT}/results/ph_tab_experiment/latest_run.txt" ]]; then
    RUN_ID="$(cat "${ROOT}/results/ph_tab_experiment/latest_run.txt")"
  fi
  ART="${ROOT}/results/ph_tab_experiment/${RUN_ID}"
}

fetch_proxy() {
  local vm=$1
  OUT="$PROXY_FILE" "${GC[@]}" compute instances describe "$vm" --zone="$ZONE" --project="$PROJECT" --format=json |
    python3 -c "
import json,sys,os
j=json.load(sys.stdin)
for it in j.get('metadata',{}).get('items',[]) or []:
    if it.get('key')=='proxy-url' and (it.get('value') or '').strip():
        open(os.environ['OUT'],'w').write(it['value'].strip()+'\n'); sys.exit(0)
sys.exit(1)
"
  chmod 600 "$PROXY_FILE"
}

next_port() {
  local taken p
  taken="$("${GC[@]}" storage ls "${PORT_PREFIX}/" 2>/dev/null | sed -n 's/.*port\.\([0-9]*\).*/\1/p' | sort -nu)"
  for p in $(seq 10000 20000); do
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
      *) echo "unknown: $1" >&2; exit 1 ;;
    esac
  done
  [[ -n "$fetch_from" ]] && fetch_proxy "$fetch_from"
  [[ -f "$PROXY_FILE" ]] || { echo "missing $PROXY_FILE; use --fetch-proxy-from" >&2; exit 1; }
  mkdir -p "$ART"
  echo "$RUN_ID" >"${ROOT}/results/ph_tab_experiment/latest_run.txt"
  : >"$ART/instances.tsv"
  for spec in "${STRATEGIES[@]}"; do
    IFS=: read -r sid tabs ramp <<<"$spec"
    name="$(vm_name "$sid")"
    port="$(next_port)"
    echo -e "${sid}\t${port}\t${tabs}\t${ramp}" >>"$ART/instances.tsv"
    echo "==> $name port=$port tabs=$tabs ramp=$ramp"
    printf '%s %s strat-%s\n' "$name" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$sid" |
      "${GC[@]}" storage cp - "${PORT_PREFIX}/port.${port}"
    meta="^;^proxy-port=${port};${COMMON_META};pdeep-tabs=${tabs};pdeep-ramp=${ramp};strat-id=${sid}"
    "${GC[@]}" compute instances create "$name" \
      --project="$PROJECT" --zone="$ZONE" \
      --machine-type=e2-standard-2 \
      --network=main-vpc --subnet=primary-subnet \
      --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=20GB \
      --service-account="$SA" --scopes=cloud-platform \
      --tags=allow-iap-ssh \
      --metadata-from-file "proxy-url=$PROXY_FILE,startup-script=$ROOT/pace_startup.sh" \
      --metadata "$meta"
  done
  date -u +%Y-%m-%dT%H:%M:%SZ >"$ART/started_at.txt"
  echo "# ts strat vm status phsuper json_count est_ppm 403_hints" >"$ART/samples.tsv"
  echo "RUN_ID=$RUN_ID  artifacts=$ART"
}

sample_one() {
  local sid=$1 name=$2 ts=$3
  local st line phsuper count ppm c403
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --project="$PROJECT" --format='value(status)' 2>/dev/null || echo MISSING)"
  if [[ "$st" != RUNNING ]]; then
    echo -e "${ts}\t${sid}\t${name}\t${st}\t-\t-\t-\t-"
    return
  fi
  line="$("${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet --command='
phsuper=$(systemctl is-active phsuper 2>/dev/null || echo unknown)
n=0
for f in /opt/ph/out/*/*.json; do [ -f "$f" ] && n=$((n+1)); done
for f in /opt/ph/out/single/*.json; do [ -f "$f" ] && n=$((n+1)); done
start=$(stat -c %Y /opt/ph/reuse/supervisor.log 2>/dev/null || stat -c %Y /var/log/phreuse_start.log 2>/dev/null || date +%s)
wall=$(( $(date +%s) - start ))
[ "$wall" -lt 60 ] && wall=60
ppm=$(python3 -c "print(round($n*60.0/$wall,4))")
c403=$(grep -cE "403|challenge|cf_clearance" /opt/ph/reuse/supervisor.log 2>/dev/null || echo 0)
echo "$phsuper $n $ppm $c403"
' 2>/dev/null)" || line="- - - -"
  read -r phsuper count ppm c403 <<<"$line"
  echo -e "${ts}\t${sid}\t${name}\t${st}\t${phsuper}\t${count}\t${ppm}\t${c403}"
}

cmd_monitor() {
  art_dir
  [[ -f "$ART/instances.tsv" ]] || { echo "no $ART/instances.tsv — run up first" >&2; exit 1; }
  local loop=0
  [[ "${1:-}" == --loop ]] && loop=1
  local end=$(( $(date +%s) + DURATION_SEC ))
  while :; do
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    while IFS=$'\t' read -r sid port tabs ramp; do
      [[ -z "$sid" ]] && continue
      sample_one "$sid" "feeder-strat-${RUN_ID}-${sid}" "$ts" | tee -a "$ART/samples.tsv"
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
for line in samples.read_text().splitlines():
    if line.startswith("#") or not line.strip():
        continue
    parts = line.split("\t")
    if len(parts) < 7:
        continue
    sid, ppm = parts[1], parts[6]
    try:
        by[sid].append(float(ppm))
    except ValueError:
        pass
print("strategy\tmean_est_ppm\tn_samples")
best = None
for sid in sorted(by):
    xs = by[sid]
    m = sum(xs) / len(xs) if xs else 0.0
    print(f"{sid}\t{m:.4f}\t{len(xs)}")
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
    "${GC[@]}" compute instances delete "feeder-strat-${RUN_ID}-${sid}" --zone="$ZONE" --quiet 2>/dev/null || true
  done <"$ART/instances.tsv"
}

case "${1:-}" in
  up) shift; cmd_up "$@" ;;
  monitor) shift; cmd_monitor "$@" ;;
  summary) cmd_summary ;;
  down) cmd_down ;;
  *)
    sed -n '2,10p' "$0" | sed 's/^# //'
    exit 1
    ;;
esac
