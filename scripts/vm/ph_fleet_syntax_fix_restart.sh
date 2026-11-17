#!/usr/bin/env bash
# Apply patch_fix_ph_batch_syntax.py (py_compile gate) + phsuper restart on listed or dead/stale slots.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
export GCP_PROJECT PACE_ZONE MVP_GCS_BUCKET
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
FLEET_LIVE_SLOTS="${FLEET_LIVE_SLOTS:-39}"
PAR="${PAR:-6}"
REMOTE=$(cat <<EOS
set -e
gcloud storage cp -q gs://${MVP_GCS_BUCKET}/usersim_sim/raw/ph_population/people_live/vm/_code/overlays/patch_fix_ph_batch_syntax.py /tmp/fix.py
sudo /opt/venv/bin/python /tmp/fix.py /opt/ph/reuse 2>/dev/null || true
sudo /opt/venv/bin/python -m py_compile /opt/ph/reuse/ph_batch.py
u=\$(tr -cd 0-9 </opt/ph/reuse/cf_cooldown_until 2>/dev/null); [ -n "\$u" ] && [ "\$u" -gt "\$(date +%s)" ] && { echo CF_COOLDOWN; exit 0; }
sudo rm -f /opt/ph/reuse/iproyal_rotate_request /opt/ph/reuse/port_override 2>/dev/null || true
sudo systemctl stop phsuper 2>/dev/null || true
sudo pkill -TERM -f "[p]deep.py|[p]h_batch.py|[c]amoufox" 2>/dev/null || true
sleep 2
EA=""; [[ -f /opt/ph/pace.env ]] && EA="\$EA -p EnvironmentFile=/opt/ph/pace.env"; [[ -f /opt/ph/strategy.env ]] && EA="\$EA -p EnvironmentFile=/opt/ph/strategy.env"
sudo systemd-run --unit=phsuper --collect -p WorkingDirectory=/opt/ph/reuse \$EA /bin/bash -c "bash /opt/ph/overlays/supervisor_strat.sh >>/opt/ph/reuse/supervisor.log 2>&1" >/dev/null 2>&1
sleep 2
echo "pdeep=\$(pgrep -cf pdeep.py || echo 0) batch=\$(pgrep -cf ph_batch.py || echo 0)"
EOS
)
mapfile -t slots < <(
  if [[ $# -gt 0 ]]; then printf '%s\n' "$@"
  else
    python3 - <<PY
import json
from pathlib import Path
m=json.loads(Path("$ART/fleet_measure.json").read_text())
live=set("$FLEET_LIVE_SLOTS".split())
for s in m.get("slots",[]):
    slot=int(s.get("slot") or 0)
    if slot in live: continue
    st=s.get("state") or ""
    if st in ("dead","stale","cf_wall") and st!="cf_wall" or (st=="cf_wall" and s.get("batch")):
        print(slot)
PY
  fi
)
[[ ${#slots[@]} -gt 0 ]] || { echo "no slots"; exit 0; }
run_slot() {
  local slot=$1 name
  name="feeder-fleet-${RUN_ID}-${slot}"
  if [[ " ${FLEET_LIVE_SLOTS} " == *" $slot "* ]]; then echo "skip live $slot"; return 0; fi
  st="$("${GC[@]}" compute instances describe "$name" --zone="$PACE_ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || { echo "slot=$slot skip status=$st"; return 0; }
  out="$("${GC[@]}" compute ssh "$name" --zone="$PACE_ZONE" --tunnel-through-iap --quiet \
    --ssh-flag=-oConnectTimeout=18 </dev/null --command="$REMOTE" 2>&1 | tail -2 | tr '\n' ' ')"
  echo "slot=$slot $out"
}
export -f run_slot
export RUN_ID PACE_ZONE REMOTE SA
export GC_CMD="$SA"
for slot in "${slots[@]}"; do
  run_slot "$slot" &
  while (( $(jobs -rp | wc -l) >= PAR )); do sleep 1; done
done
wait
echo "syntax_fix_restart done n=${#slots[@]}"