#!/usr/bin/env bash
# Raise active slot count: restart phsuper on dead/cf_wall VMs without full IPRoyal geo churn.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PACE_REPO_ROOT="$ROOT"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt" 2>/dev/null)}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
[[ -f "$ART/fleet_measure.json" ]] || exit 0
MAX="${FLEET_WAKEUP_MAX:-10}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:?}"

mapfile -t targets < <(python3 - <<PY
import json
from pathlib import Path
m=json.loads(Path("$ART/fleet_measure.json").read_text())
dead, cf = [], []
for s in m.get("slots", []):
    slot=int(s.get("slot") or 0)
    st=s.get("state") or ""
    if st == "dead":
        dead.append(slot)
    elif st == "cf_wall" and s.get("batch"):
        cf.append(slot)
# Dead first, then cf_wall still running batch
print("\\n".join(str(x) for x in (dead + cf)[:int("$MAX")]))
PY
)

REMOTE='sudo rm -f /opt/ph/reuse/cf_cooldown_until /opt/ph/reuse/cf_backoff_n /opt/ph/reuse/same_tok_retry_at /opt/ph/reuse/iproyal_rotate_request 2>/dev/null
pgrep -f "[p]h_batch.py|[p]deep.py" >/dev/null || sudo systemctl restart phsuper'

n=0
for slot in "${targets[@]}"; do
  [[ -z "$slot" ]] && continue
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || continue
  "${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet \
    --ssh-flag=-oConnectTimeout=12 </dev/null --command="$REMOTE" 2>/dev/null && {
    echo "wakeup slot=$slot"
    n=$((n + 1))
  } &
  (( n % 5 == 0 )) && wait
done
wait
echo "fleet_wakeup n=$n"
