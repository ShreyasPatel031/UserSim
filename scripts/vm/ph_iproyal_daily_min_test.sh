#!/usr/bin/env bash
# Find minimum ISP IPs for daily browser work: probe VMs + short soaks at L0/L1/daily_steady.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PATH="/home/ubuntu/google-cloud-sdk/bin:${PATH:-}"
PROJECT="${GCP_PROJECT:?}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:-$("${GC[@]}" compute instances list --project="$PROJECT" --filter='name~feeder-fleet' --limit=1 --format='value(zone)')}"
[[ -n "$ZONE" ]] || { echo "PACE_ZONE required" >&2; exit 1; }
BUCKET="${MVP_GCS_BUCKET:?}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
POOL="${PACE_IPROYAL_POOL:-$ROOT/secrets/iproyal.pool}"
SOAK_MIN="${DAILY_SOAK_MIN:-10}"
WARMUP_SEC="${DAILY_WARMUP_SEC:-180}"
ART_OUT="$ROOT/results/ph_iproyal_limit/daily_min_test_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ART_OUT" "$ART"

merge_env() {
  local level=$1 out="$ART_OUT/strategy_${level}.env"
  { cat "$ROOT/scripts/vm/ph_strategies/iproyal/_base.env"; echo; cat "$ROOT/scripts/vm/ph_strategies/iproyal/${level}.env"; } >"$out"
  echo "$out"
}

read_pool() {
  mapfile -t PURLS < <(grep -v '^[[:space:]]*#' "$POOL" | grep -v '^[[:space:]]*$' || true)
  ((${#PURLS[@]} >= 1)) || { echo "empty $POOL" >&2; exit 1; }
}

_purl_abs() {
  local p=$1
  [[ "$p" = /* ]] && echo "$p" || echo "$ROOT/$p"
}

sample_slot() {
  local slot=$1 win=${2:-600}
  local name="feeder-fleet-${RUN_ID}-${slot}"
  "${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet </dev/null --command="python3 <<'PY'
import json, os, socket, time
from datetime import datetime, timezone
W=${win}
now=time.time()
host=socket.gethostname()
path=f'/opt/ph/reuse/status_{host}.jsonl'
def ts(u):
    try: return datetime.fromisoformat(u.replace('Z','+00:00')).timestamp()
    except Exception: return None
lines=open(path).read().splitlines() if os.path.isfile(path) else []
browser_ok=browser_fail=0
nc=nr=gql429=walls=0
for ln in lines:
    try: j=json.loads(ln)
    except Exception: continue
    ev=j.get('event'); t=ts(j.get('utc') or '')
    if ev=='browser_open' and t and now-t<W:
        if j.get('ok'): browser_ok+=1
        else: browser_fail+=1
    if not t or now-t>W: continue
    rc=j.get('rc')
    if j.get('handle') and rc is not None:
        ok = rc==0 and ev!='incomplete_skip_upload' and str(j.get('method') or '').startswith('pfull')
        if ok: nc+=1
        else: nr+=1
        if rc==3 and '429' in (j.get('detail') or ''): gql429+=1
    elif ev in ('stopped_on_block','browser_open_failed') or (ev=='supervisor_run_end' and rc==3):
        walls+=1
m=max(W/60.0, 1/60.0)
print(json.dumps({'complete_ppm':round(nc/m,3),'attempt_ppm':round((nc+nr)/m,3),'gql429':gql429,'walls':walls,
'browser_ok_10m':browser_ok,'browser_fail_10m':browser_fail}))
PY" 2>/dev/null || echo '{"ssh_fail":true}'
}

soak_one() {
  local slot=$1 purl=$2 level=$3 tag=$4
  local name="feeder-fleet-${RUN_ID}-${slot}" strat
  strat="$(merge_env "$level")"
  purl="$(_purl_abs "$purl")"
  [[ -f "$purl" ]] || { echo "missing $purl" >&2; return 1; }
  echo "=== soak slot=$slot ip=$(sed -E 's|.*@([^:]+):.*|\1|' "$purl") level=$level tag=$tag ==="
  "${GC[@]}" compute instances add-metadata "$name" --zone="$ZONE" \
    --metadata-from-file="proxy-url=$purl,ph-strategy-env=$strat" >/dev/null
  ONLY_SLOTS="$slot" PH_FLEET_STRATEGY_ENV="$strat" bash "$ROOT/scripts/vm/ph_fleet_roll_patches.sh" | tail -2
  "${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet </dev/null \
    --command='sudo systemctl restart phsuper 2>/dev/null || true' || true
  echo "warmup ${WARMUP_SEC}s..."
  sleep "$WARMUP_SEC"
  local j
  j="$(sample_slot "$slot" $((SOAK_MIN * 60)))"
  python3 - <<PY "$tag" "$level" "$purl" "$j" "$ART_OUT/soak.tsv"
import json, sys
from pathlib import Path
from urllib.parse import urlparse
tag, level, purl, j, out = sys.argv[1:6]
m=json.loads(j)
ip=urlparse(open(purl).read().strip()).hostname or '?'
row=[tag, ip, level, str(m.get('complete_ppm')), str(m.get('attempt_ppm')),
     str(m.get('gql429')), str(m.get('walls')), str(m.get('browser_ok_10m')), str(m.get('browser_fail_10m'))]
Path(out).parent.mkdir(parents=True, exist_ok=True)
p=Path(out)
if not p.exists(): p.write_text('# tag\tip\tlevel\tcomplete_ppm\tattempt_ppm\tgql429\twalls\tbrowser_ok\tbrowser_fail\n')
p.open('a').write('\t'.join(row)+'\n')
print('\t'.join(row))
PY
}

cmd_probe_ips() {
  read_pool
  echo "# idx	ip	plain_probe_vm_note" >"$ART_OUT/ip_probe.tsv"
  local i=1
  for p in "${PURLS[@]}"; do
    p="$(_purl_abs "$p")"
    ip=$(python3 -c "import urllib.parse as u; print(u.urlparse(open('$p').read().strip().split('@')[-1]).hostname)")
    echo -e "$i\t$ip\tsee_vm_soak" >>"$ART_OUT/ip_probe.tsv"
    i=$((i + 1))
  done
  cat "$ART_OUT/ip_probe.tsv"
}

cmd_serial_probe() {
  read_pool
  cmd_probe_ips >/dev/null
  local slot=1
  for i in "${!PURLS[@]}"; do
    soak_one "$slot" "${PURLS[$i]}" L0_ultra "probe_fi_$((i+1))"
  done
  echo "artifacts $ART_OUT"
}

cmd_min_test() {
  read_pool
  echo "$ART_OUT" >"$ROOT/results/ph_iproyal_limit/daily_min_latest.txt"
  cmd_probe_ips
  # 1 IP steady (daily_steady = L2 shape)
  soak_one 1 "${PURLS[0]}" daily_steady "n1_daily_steady"
  # 1 IP politest full ladder point still under daily GQL volume
  soak_one 1 "${PURLS[0]}" L1_polite "n1_L1_polite"
  # 2 IP parallel if slot 2 exists or create
  have=$(awk 'NF>=2 && $1+0==$1' "$ART/slots.tsv" 2>/dev/null | wc -l)
  if [[ "$have" -lt 2 ]]; then
    export PACE_PROXY_FILE="$(_purl_abs "${PURLS[1]}")"
    export PH_FLEET_STRATEGY="$(merge_env daily_steady)"
    FLEET_MIN_VMS=0 FLEET_MAX_VMS=2 PACE_FLEET_RUN_ID="$RUN_ID" \
      bash "$ROOT/scripts/vm/ph_fleet_autoscale.sh" scale-to 2
  fi
  soak_one 1 "${PURLS[0]}" daily_steady "n2_slot1" &
  soak_one 2 "${PURLS[1]:-${PURLS[0]}}" daily_steady "n2_slot2" &
  wait
  python3 "$ROOT/scripts/vm/ph_iproyal_daily_min_report.py" "$ART_OUT" || true
}

case "${1:-min_test}" in
  probe) cmd_serial_probe ;;
  min_test) cmd_min_test ;;
  *) echo "usage: $0 probe|min_test" >&2; exit 1 ;;
esac
