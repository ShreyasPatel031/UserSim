#!/usr/bin/env bash
# CF-wall = identity_ready but no first_pull: port-rotate + batch restart within KEEPER_DEAD_SEC.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt")}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="$PACE_ZONE"
MAX_WAIT_SEC="${CF_WALL_MAX_SEC:-180}"
VM_GCS="${PACE_VM_GCS:-gs://${MVP_GCS_BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"
GO_TOKEN="run:fleet-${RUN_ID}"

REMOTE='
python3 <<PY
import json, socket, time, subprocess
from pathlib import Path
from datetime import datetime, timezone
host=socket.gethostname()
fp=idr=None
for ln in Path("/opt/ph/reuse/setup_timing.jsonl").read_text().splitlines():
    try: j=json.loads(ln)
    except: continue
    if j.get("event")=="first_pull": fp=j.get("utc")
    if j.get("event")=="identity_ready": idr=j.get("utc")
if fp:
    print("OK already first_pull"); raise SystemExit(0)
if not idr:
    print("WAIT no identity"); raise SystemExit(0)
t=datetime.fromisoformat(idr.replace("Z","+00:00"))
age=(datetime.now(timezone.utc)-t).total_seconds()
print(f"CF_WALL age_since_identity={int(age)}s")
if age < '"$MAX_WAIT_SEC"':
    print("WAIT under threshold"); raise SystemExit(0)
# Force new sticky port + restart batch
import os
os.environ["PH_PORTSCREEN_HOME_ONLY"]="0"
os.environ["PH_PORTSCREEN_MAX_TRY"]="12"
try:
    import portscreen as ps
    home=int(os.environ.get("PROXY_PORT") or 0)
    if home:
        ps.FAILED.add(home)
        try: ps._release(home, host)
        except: pass
    np=ps.prescreen(host, lambda **kw: None)
    print("NEW_PORT", np)
except Exception as e:
    print("PORT_ERR", e)
subprocess.call(["pkill","-f","ph_batch.py"])
time.sleep(2)
print("BATCH_KILLED")
PY
'

while IFS=$'\t' read -r slot _port; do
  [[ -z "$slot" || "$slot" == \#* ]] && continue
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || continue
  out="$("${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet \
    --ssh-flag=-oConnectTimeout=15 </dev/null --command="$REMOTE" 2>/dev/null)" || continue
  if echo "$out" | grep -q "BATCH_KILLED"; then
    echo "$GO_TOKEN" | "${GC[@]}" storage cp - "${VM_GCS}/GO.${name}" 2>/dev/null || true
    echo "==> cf_recover slot=$slot $(echo "$out" | tr '\n' ' ')"
  fi
done <"$ART/slots.tsv"
