#!/usr/bin/env bash
# Stop phsuper on idle historical fleet slots (VMs stay up; IPs unchanged). Exempt upvote + live capture.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
MEASURE="$ART/fleet_measure.json"
[[ -f "$MEASURE" ]] || { echo "missing $MEASURE" >&2; exit 1; }
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:?}"
STRATEGY="${PH_FLEET_STRATEGY:-$ROOT/scripts/vm/ph_strategies/fleet_optimize.env}"
EXEMPT="${FLEET_UPVOTE_SLOTS:-9 27 38} ${FLEET_LIVE_SLOTS:-39}"
PAUSE_ENV="$ART/fleet_strategy_pause.env"
grep -v '^PH_FLEET_BLOCK_PAUSE=' "$STRATEGY" >"$PAUSE_ENV" 2>/dev/null || cp "$STRATEGY" "$PAUSE_ENV"
echo 'PH_FLEET_BLOCK_PAUSE=1' >>"$PAUSE_ENV"

mapfile -t slots < <(python3 - <<PY
import json
from pathlib import Path
ex = {int(x) for x in """$EXEMPT""".split() if x.strip().isdigit()}
m = json.loads(Path("$MEASURE").read_text())
for s in m.get("slots", []):
    slot = int(s.get("slot") or 0)
    if slot in ex:
        continue
    if (s.get("state") or "") == "active":
        continue
    print(slot)
PY
)

REMOTE='sudo systemctl stop phsuper 2>/dev/null || true
sudo pkill -TERM -f "[p]deep.py|[p]h_batch.py" 2>/dev/null || true
sleep 1
echo PHSUPER_STOPPED'

for slot in "${slots[@]}"; do
  [[ -z "$slot" ]] && continue
  name="feeder-fleet-${RUN_ID}-${slot}"
  if ! "${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='get(status)' 2>/dev/null | grep -q RUNNING; then
    echo "skip slot=$slot (not RUNNING)"
    continue
  fi
  "${GC[@]}" compute instances add-metadata "$name" --zone="$ZONE" \
    --metadata-from-file="ph-strategy-env=$PAUSE_ENV" >/dev/null 2>&1 || true
  echo "pause slot=$slot"
  "${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet </dev/null --command="$REMOTE" 2>/dev/null \
    || echo "ssh pause failed slot=$slot"
done
echo "paused_slots=${#slots[@]} exempt=$EXEMPT"