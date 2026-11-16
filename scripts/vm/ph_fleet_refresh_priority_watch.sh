#!/usr/bin/env bash
# Apply priority merge when files land; relay orchestrator when first priority day is drained.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export GCP_PROJECT PACE_ZONE MVP_GCS_BUCKET PACE_FLEET_RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
ART="$ROOT/results/ph_fleet_full/${PACE_FLEET_RUN_ID,,}"
export FLEET_ART="$ART" AGENT_MSGS_PROJECT="$GCP_PROJECT"

bash "$ROOT/scripts/vm/ph_fleet_apply_refresh_priority.sh"

while true; do
  if python3 "$ROOT/scripts/vm/ph_fleet_refresh_priority_progress.py" >/tmp/rp_prog.json; then
    DAY="$(python3 -c "import json;print(json.load(open('/tmp/rp_prog.json'))['first_priority_day'])")"
    DONE="$(python3 -c "import json;d=json.load(open('/tmp/rp_prog.json'));print(d['done_n'],d['priority_n'],d['done_pct'])")"
    MSG="UPVOTE_REFRESH_PRIORITY_DONE refresh_priority_${DAY}.txt drain complete (${DONE}). Queue was priority-days 13-14-15 then activity tail; slots 9/27/38 repullupvotes unchanged policy."
    bash "$ROOT/scripts/vm/ph_fleet_agent_relay.sh" orchestrator fleet-cursor "$MSG"
    python3 <<PY
import json
from pathlib import Path
p=Path("$ART/upvote_refresh_priority.state.json")
s=json.loads(p.read_text())
s["orchestrator_done_relayed"]=True
s["done_utc"]="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
p.write_text(json.dumps(s,indent=2))
PY
    echo "DONE relay sent"
    exit 0
  fi
  if [[ -f "$ART/upvote_refresh_priority.state.json" ]]; then
    python3 -c "import json; d=json.load(open('$ART/upvote_refresh_priority.state.json')); print('progress', d.get('first_priority_day'), 'waiting...')" || true
  fi
  sleep 120
done