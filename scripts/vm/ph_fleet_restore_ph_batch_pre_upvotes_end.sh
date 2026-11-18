#!/usr/bin/env bash
# Restore ph_batch.py + paging_v2.py from reuse.tgz (pre upvotes_ph_end overlay) and restart phsuper.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
LIVE="${FLEET_LIVE_SLOTS:-39}"
if [[ $# -gt 0 ]]; then
  slots=("$@")
else
  mapfile -t slots < <(awk -F'\t' 'NF{print $1}' "$ART/slots.tsv" | grep -vxE "$LIVE" || true)
fi
REMOTE_SCRIPT=$(cat <<'EOS'
set -e
B=$(grep -E '^PACE_GCS_VM_ROOT=' /opt/ph/pace.env | cut -d= -f2-)
TMPD=/tmp/reuse_restore_$$
mkdir -p "$TMPD"
gsutil -q cp "$B/_code/reuse.tgz" "$TMPD/reuse.tgz"
tar xzf "$TMPD/reuse.tgz" -C "$TMPD" ph_batch.py paging_v2.py
sudo cp -f "$TMPD/ph_batch.py" "$TMPD/paging_v2.py" /opt/ph/reuse/
rm -rf "$TMPD"
sudo /opt/venv/bin/python -m py_compile /opt/ph/reuse/ph_batch.py /opt/ph/reuse/paging_v2.py
sudo rm -f /opt/ph/reuse/cf_cooldown_until /opt/ph/reuse/cf_backoff_n /opt/ph/reuse/same_tok_retry_at /opt/ph/reuse/iproyal_rotate_request /opt/ph/reuse/port_override 2>/dev/null || true
sudo systemctl stop phsuper 2>/dev/null || true
sudo pkill -TERM -f "[p]deep.py|[p]h_batch.py|[c]amoufox" 2>/dev/null || true
sleep 2
EA=""; [[ -f /opt/ph/pace.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/pace.env"; [[ -f /opt/ph/strategy.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/strategy.env"
sudo systemd-run --unit=phsuper --collect -p WorkingDirectory=/opt/ph/reuse $EA \
  /bin/bash -c "bash /opt/ph/overlays/supervisor_strat.sh >>/opt/ph/reuse/supervisor.log 2>&1" >/dev/null 2>&1
echo "restore_ok pdeep=$(pgrep -cf pdeep.py 2>/dev/null || echo 0)"
EOS
)
run_one() {
  local slot=$1 name rc=0
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$PACE_ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || { echo "slot=$slot skip status=$st"; return 0; }
  out="$("${GC[@]}" compute ssh "$name" --zone="$PACE_ZONE" --tunnel-through-iap --quiet </dev/null \
    --command='bash -s' <<<"$REMOTE_SCRIPT" 2>&1)" || rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "slot=$slot FAIL ${out##*$'\n'}"
  else
    echo "slot=$slot $(echo "$out" | tail -1)"
  fi
}
for slot in "${slots[@]}"; do
  run_one "$slot"
  sleep 2
done
echo "restore_pre_upvotes_end done n=${#slots[@]}"