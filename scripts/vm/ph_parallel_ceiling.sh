#!/usr/bin/env bash
# One-browser parallel ceiling: reuse feeder-strat VMs as 16/32/48/64 tab arms.
#   ./scripts/vm/ph_parallel_ceiling.sh start
#   ./scripts/vm/ph_parallel_ceiling.sh sample
#   ./scripts/vm/ph_parallel_ceiling.sh summary
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT="${GCP_PROJECT:?}"
ZONE="${PACE_ZONE:?}"
BUCKET="${MVP_GCS_BUCKET:?}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${PROJECT}.iam.gserviceaccount.com}"
[[ -d /home/ubuntu/google-cloud-sdk/bin ]] && export PATH="/home/ubuntu/google-cloud-sdk/bin:$PATH"
GC=(gcloud --account="$SA")
RUN_ID="${PACE_CEILING_BASE_RUN:-20261107t170953z}"
ART_ROOT="${ROOT}/results/ph_parallel_ceiling"
VM_GCS="gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm"

ARMS=(
  "a:16:${ROOT}/scripts/vm/ph_strategies/ceiling_16.env"
  "b:32:${ROOT}/scripts/vm/ph_strategies/ceiling_32.env"
  "c:48:${ROOT}/scripts/vm/ph_strategies/ceiling_48.env"
  "d:64:${ROOT}/scripts/vm/ph_strategies/ceiling_64.env"
)
vm() { echo "feeder-strat-${RUN_ID}-${1}"; }

art_dir() {
  if [[ -f "${ART_ROOT}/latest.txt" ]]; then
    ART="$(cat "${ART_ROOT}/latest.txt")"
  else
    echo "no ceiling run; start first" >&2
    exit 1
  fi
}

cmd_start() {
  mkdir -p "$ART_ROOT"
  ART="${ART_ROOT}/$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$ART"
  echo "$ART" >"${ART_ROOT}/latest.txt"
  GO_TOKEN="run:ceiling-$(date -u +%Y%m%dT%H%M%SZ)"
  GO_TOKEN="${GO_TOKEN,,}"
  echo "$GO_TOKEN" >"$ART/go_token.txt"
  date -u +%Y-%m-%dT%H:%M:%SZ >"$ART/started_at.txt"
  echo -e "sid\ttabs\tvm\tenv" >"$ART/arms.tsv"
  echo "# ts tabs vm phsuper json blocks runtime_port args note" >"$ART/samples.tsv"

  # Overlays + per-arm ceiling env + relaunch helper (SSH dies if pkill is inline).
  "${GC[@]}" storage cp \
    "$ROOT/scripts/vm/reuse_overlays/supervisor_strat.sh" \
    "$ROOT/scripts/vm/reuse_overlays/portscreen.py" \
    "$ROOT/scripts/vm/reuse_overlays/strategy_args.py" \
    "$ROOT/scripts/vm/reuse_overlays/ensure_geoip.sh" \
    "$ROOT/scripts/vm/reuse_overlays/patch_week_bytes.py" \
    "$ROOT/scripts/vm/reuse_overlays/ceiling_relaunch.sh" \
    "${VM_GCS}/_code/overlays/" >/dev/null
  cat >"$ART/ceiling_relaunch.sh" <<'EOS'
#!/bin/bash
set +e
TABS="${1:?tabs}"
B=$(grep PACE_GCS_VM_ROOT /opt/ph/pace.env | cut -d= -f2-)
gcloud storage cp -q "$B/_code/overlays/supervisor_strat.sh" "$B/_code/overlays/portscreen.py" \
  "$B/_code/overlays/strategy_args.py" "$B/_code/overlays/ensure_geoip.sh" \
  "$B/_code/overlays/patch_week_bytes.py" /opt/ph/overlays/
gcloud storage cp -q "$B/_code/overlays/ceiling_${TABS}.env" /opt/ph/strategy.env
chmod +x /opt/ph/overlays/ensure_geoip.sh /opt/ph/overlays/supervisor_strat.sh
PACE_GCS_VM_ROOT="$B" bash /opt/ph/overlays/ensure_geoip.sh
cp -f /opt/ph/overlays/portscreen.py /opt/ph/reuse/portscreen.py
cp -f /opt/ph/overlays/strategy_args.py /opt/ph/reuse/strategy_args.py
# Ensure supervisor re-applies week_bytes patch after each reuse.tgz unpack
if ! grep -q patch_week_bytes /opt/ph/overlays/supervisor_strat.sh; then
  awk '
    /apply_overlays/ && !done {
      print
      print "  gcloud storage cp -q \"$B/_code/overlays/patch_week_bytes.py\" /opt/ph/overlays/ 2>/dev/null || true"
      print "  /opt/venv/bin/python /opt/ph/overlays/patch_week_bytes.py >> supervisor.log 2>&1 || true"
      done=1; next
    }
    { print }
  ' /opt/ph/overlays/supervisor_strat.sh > /tmp/sup.sh && mv /tmp/sup.sh /opt/ph/overlays/supervisor_strat.sh
fi
sed -i -E '/^PH_(STRATEGY|TABS|BROWSER_TABS|MAX_INFLIGHT|RAMP|REQ_PER_MIN|PERSON_INTERVAL|START_|AIMD_|BURST_|COAST_|LAZY_|CIRCUIT_|INTER_REQ|SKIP_|SERIALIZE_)/d' /opt/ph/pace.env
grep -q PH_PORTSCREEN_HOME_ONLY= /opt/ph/pace.env || echo PH_PORTSCREEN_HOME_ONLY=1 >> /opt/ph/pace.env
systemctl stop phsuper 2>/dev/null || true
pkill -f ph_batch.py 2>/dev/null || true
sleep 1
rm -f /opt/ph/reuse/last_token
rm -rf /opt/ph/profiles
mkdir -p /opt/ph/profiles /opt/ph/golden_quarantine
mv /opt/ph/reuse/out "/opt/ph/golden_quarantine/out.ceiling_relaunch.$(date -u +%Y%m%dT%H%M%SZ)" 2>/dev/null || true
mkdir -p /opt/ph/reuse/out
: > /opt/ph/reuse/setup_timing.jsonl
# Patch current tree before start (supervisor will re-patch after unpack)
/opt/venv/bin/python /opt/ph/overlays/patch_week_bytes.py || true
set -a; source /opt/ph/pace.env; source /opt/ph/strategy.env; set +a
echo -n "args="; /opt/venv/bin/python /opt/ph/reuse/strategy_args.py; echo
grep -n "WEEK_BYTES_CACHE\|ceiling" /opt/ph/reuse/ph_batch.py | head -5
systemd-run --unit=phsuper --collect -p WorkingDirectory=/opt/ph/reuse \
  -p EnvironmentFile=/opt/ph/pace.env -p EnvironmentFile=/opt/ph/strategy.env \
  /bin/bash -c 'bash /opt/ph/overlays/supervisor_strat.sh >> /opt/ph/reuse/supervisor.log 2>&1'
sleep 1
systemctl is-active phsuper || true
echo DONE
EOS
  "${GC[@]}" storage cp "$ART/ceiling_relaunch.sh" "${VM_GCS}/_code/overlays/ceiling_relaunch.sh" >/dev/null

  for spec in "${ARMS[@]}"; do
    IFS=: read -r sid tabs envf <<<"$spec"
    name="$(vm "$sid")"
    echo -e "${sid}\t${tabs}\t${name}\t$(basename "$envf")" >>"$ART/arms.tsv"
    echo "==> ceiling tabs=$tabs on $name"
    "${GC[@]}" storage cp "$envf" "${VM_GCS}/_code/overlays/ceiling_${tabs}.env" >/dev/null
    # Supervisor reloads strategy from instance metadata each launch — keep it in sync.
    "${GC[@]}" compute instances add-metadata "$name" --zone="$ZONE" --project="$PROJECT" \
      --metadata-from-file="ph-strategy-env=${envf}" >/dev/null
    set +e
    "${GC[@]}" compute ssh "$name" --zone="$ZONE" --project="$PROJECT" --tunnel-through-iap --quiet \
      --command="sudo bash -c 'set +e; B=\$(grep PACE_GCS_VM_ROOT /opt/ph/pace.env | cut -d= -f2-); gcloud storage cp -q \$B/_code/overlays/ceiling_relaunch.sh /tmp/ceiling_relaunch.sh; chmod +x /tmp/ceiling_relaunch.sh; bash /tmp/ceiling_relaunch.sh ${tabs}'" \
      </dev/null 2>&1 | grep -vE 'NumPy|setlocale|WARNING:|cloud.google.com/iap|To increase|Warning: Permanently|known hosts' | tail -20
    set -e
    echo "$GO_TOKEN" | "${GC[@]}" storage cp - "${VM_GCS}/GO.${name}"
  done
  echo "GO=$GO_TOKEN"
  echo "ART=$ART"
}

sample_one() {
  local tabs=$1 name=$2 ts=$3
  local remote line
  remote='phsuper=$(systemctl is-active phsuper 2>/dev/null || echo no)
n=$(find /opt/ph/reuse/out -name "*.json" ! -name "_*" ! -name hb.json 2>/dev/null | wc -l)
c403=0
for f in /opt/ph/reuse/run_*.log; do [ -f "$f" ] || continue; c403=$((c403+$(grep -cE "BLOCK|challenge not cleared" "$f" 2>/dev/null || true))); done
rport=$(grep -E "FINGERPRINT_(NEW|REUSED)" /opt/ph/reuse/run_*.log 2>/dev/null | tail -1 | grep -oE "port [0-9]+" | awk "{print \$2}")
[ -z "$rport" ] && rport=$(curl -sf -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/instance/attributes/proxy-port)
sargs=$(grep -E "^launch " /opt/ph/reuse/supervisor.log 2>/dev/null | tail -1 | sed -n "s/.*extra=\[\(.*\)\].*/\1/p" | tr " " _)
note=$(grep -E "RAMP |BLOCK |FINGERPRINT_" /opt/ph/reuse/run_*.log 2>/dev/null | tail -1 | tr " \t" "__" | cut -c1-100)
echo "$phsuper $n $c403 ${rport:-?} ${sargs:-?} ${note:-.}"'
  line="$("${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet --command="$remote" </dev/null 2>/dev/null)" || line="no 0 0 ? ? ."
  local phsuper n c403 rport sargs note
  read -r phsuper n c403 rport sargs note <<<"$line"
  echo -e "${ts}\t${tabs}\t${name}\t${phsuper:--}\t${n:--}\t${c403:--}\t${rport:--}\t${sargs:--}\t${note:--}"
}

cmd_sample() {
  art_dir
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  while IFS=$'\t' read -r sid tabs name _env; do
    [[ "$sid" == "sid" || -z "$sid" ]] && continue
    sample_one "$tabs" "$name" "$ts" | tee -a "$ART/samples.tsv"
  done <"$ART/arms.tsv"
}

cmd_summary() {
  art_dir
  python3 - <<'PY' "$ART"
import sys
from pathlib import Path
from collections import defaultdict
art = Path(sys.argv[1])
by = defaultdict(list)
last = {}
for line in (art/"samples.tsv").read_text().splitlines():
    if line.startswith("#") or not line.strip():
        continue
    p = line.split("\t")
    if len(p) < 6:
        continue
    tabs, n, c403, port, args = p[1], p[4], p[5], p[6], p[7]
    try:
        by[tabs].append(int(n))
        last[tabs] = (int(n), int(c403), port, args)
    except ValueError:
        pass
print("tabs\tlast_json\tmax_json\t403_hints\tport\targs")
best = None
for tabs in sorted(by, key=lambda x: int(x)):
    xs = by[tabs]
    n, c403, port, args = last[tabs]
    print(f"{tabs}\t{n}\t{max(xs)}\t{c403}\t{port}\t{args}")
    score = (n, -c403)
    if best is None or score > best[1]:
        best = (tabs, score, c403)
if best:
    print(f"\nBEST_THROUGHPUT: {best[0]} tabs (json={best[1][0]}, blocks={best[2]})")
    # cliff = highest tabs that still produced json with blocks not exploding vs 16
    print(f"ART={art}")
PY
}

case "${1:-}" in
  start) cmd_start ;;
  sample) cmd_sample ;;
  summary) cmd_summary ;;
  *) echo "usage: $0 start|sample|summary"; exit 1 ;;
esac
