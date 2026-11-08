#!/usr/bin/env bash
# CF wall = batch running but no person saved/attempted for CF_WALL_MAX_SEC since its start.
# Kick: write /opt/ph/reuse/KICK and stop the batch; supervisor_strat.sh then screens a new free port and relaunches
# the same GO token (a rewritten identical token alone never relaunches).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt")}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="$PACE_ZONE"
MAX_WAIT_SEC="${CF_WALL_MAX_SEC:-300}"

REMOTE='
python3 <<PY
import json, socket, subprocess, time
from datetime import datetime, timezone
host=socket.gethostname()
now=time.time()
def ts(u):
    try: return datetime.fromisoformat(u.replace("Z","+00:00")).timestamp()
    except Exception: return None
start=None; last_person=None
try: rows=open(f"/opt/ph/reuse/status_{host}.jsonl").read().splitlines()
except Exception: rows=[]
for ln in rows:
    try: j=json.loads(ln)
    except Exception: continue
    t=ts(j.get("utc") or "")
    if not t: continue
    if j.get("event")=="start": start=t
    if j.get("handle") and j.get("rc") is not None: last_person=t
running=subprocess.call(["pgrep","-f","[p]deep.py|[p]h_batch.py"],stdout=subprocess.DEVNULL)==0
if not running: print("WAIT no batch"); raise SystemExit(0)
ref=max(x for x in (start, last_person, 0) if x is not None)
if not ref: print("WAIT no start row"); raise SystemExit(0)
idle=int(now-ref)
print(f"idle={idle}s")
if idle < '"$MAX_WAIT_SEC"' or (last_person and start and last_person>=start and idle<900):
    print("OK"); raise SystemExit(0)
subprocess.call(["sudo","sh","-c","date -u +%FT%TZ > /opt/ph/reuse/KICK"])
subprocess.call(["sudo","pkill","-TERM","-f","[p]deep.py|[p]h_batch.py"])
print("BATCH_KICKED")
PY
'

while IFS=$'\t' read -r slot _port; do
  [[ -z "$slot" || "$slot" == \#* ]] && continue
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || continue
  out="$("${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet \
    --ssh-flag=-oConnectTimeout=15 </dev/null --command="$REMOTE" 2>/dev/null)" || continue
  if echo "$out" | grep -q "BATCH_KICKED"; then
    echo "==> cf_recover slot=$slot $(echo "$out" | tr '\n' ' ')"
  fi
done <"$ART/slots.tsv"
