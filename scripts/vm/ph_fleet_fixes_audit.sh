#!/usr/bin/env bash
# Babysit: verify pdeep + overlays + strategy on every running fleet slot; optional re-roll broken slots.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt")}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
ZONE="$PACE_ZONE"
REPAIR="${FLEET_FIXES_REPAIR:-1}"
PROBE="$ROOT/scripts/vm/fleet_fixes_probe_remote.sh"

probe_one() {
  local slot=$1 name line ok
  name="feeder-fleet-${RUN_ID}-${slot}"
  line="$(gcloud --account="$SA" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet \
    --ssh-flag=-oConnectTimeout=10 </dev/null --command="bash -s" <"$PROBE" 2>/dev/null || echo '{"ok":false,"why":["ssh_fail"]}')"
  ok="$(echo "$line" | python3 -c "import json,sys; print(1 if json.load(sys.stdin).get('ok') else 0)" 2>/dev/null || echo 0)"
  if [[ "$ok" == 1 ]]; then echo "OK $slot"
  else echo "BAD $slot $line"; fi
}
export -f probe_one
export RUN_ID SA ZONE PROBE

slots=()
while IFS=$'\t' read -r slot _; do
  [[ -z "$slot" || "$slot" == \#* ]] && continue
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$(gcloud --account="$SA" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || continue
  slots+=("$slot")
done <"$ART/slots.tsv"
total=${#slots[@]}
tmp="$(mktemp)"
printf '%s\n' "${slots[@]}" | xargs -P 10 -I{} bash -c 'probe_one "$@"' _ {} >"$tmp" 2>/dev/null || true
good=$(grep -c '^OK ' "$tmp" 2>/dev/null || true); good=${good:-0}
bad=()
while read -r tag slot rest; do
  [[ "$tag" == BAD ]] && bad+=("$slot") && echo "FIXES_BAD slot=$slot $rest"
done <"$tmp"
rm -f "$tmp"

python3 - <<PY >"$ART/fixes_audit.json"
import json
from datetime import datetime, timezone
bad = $(printf '%s\n' "${bad[@]:-}" | python3 -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))")
print(json.dumps({"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "total": $total, "good": $good, "bad_slots": bad}, indent=2))
PY

if [[ "$REPAIR" == 1 && ${#bad[@]} -gt 0 && ${#bad[@]} -le 12 ]]; then
  ONLY_SLOTS="${bad[*]}" SKIP_UPLOAD=1 bash "$ROOT/scripts/vm/ph_fleet_roll_patches.sh" >>"$ART/checkin.log" 2>&1 || true
  echo "FIXES_REPAIR rolled slots: ${bad[*]}"
fi
echo "FIXES_AUDIT good=$good/$total bad=${bad[*]:-none}"
