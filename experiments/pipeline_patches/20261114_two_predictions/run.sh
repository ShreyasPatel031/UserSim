#!/bin/bash
# Bundle 12a runner on usersim-pipeline: rec (extra recorder read) | midnight | prereveal. One flock per job; one log line per run to
# /home/agent/w/tw12a/logs/<day>.log, copied to gs://.../results/timed_writes/<day>_12a.log.
set -uo pipefail
J=${1:?job}; TW=/home/agent/w/tw12a; B=gs://usersim-bakeoff-347838016394/usersim_sim
export PATH=/opt/exp/bin:$PATH TZ=America/Los_Angeles; D=$(date +%F); mkdir -p $TW/logs $TW/locks
exec 8>$TW/locks/$J.lock; flock -n 8 || exit 0
case "$J" in
rec)   # same token source as run_daily.sh; never echoed
  export PH_TOKEN=$(python3 -c "import json; print(json.load(open('/var/lib/usersim/discovery_keys.json'))['PH_TOKEN'])")
  ST=$(cd /home/agent/w/experiments && timeout 300 python3 $TW/recorder_extra.py 2>&1 | tail -1 | cut -c1-200); unset PH_TOKEN;;
midnight)   # waits up to 40 min for the pipeline's forecast parquet (no API call, no model run)
  for i in $(seq 1 80); do [ -f /home/agent/w/experiments/ph_predict/results/forecast_$D.parquet ] && break; sleep 30; done
  ST=$(timeout 300 python3 $TW/two_predictions.py midnight $D 2>&1 | tail -1 | cut -c1-300);;
prereveal)
  ST=$(timeout 300 python3 $TW/two_predictions.py prereveal $D 2>&1 | tail -1 | cut -c1-300);;
*) echo "unknown job"; exit 2;;
esac
echo "$J $D written at $(date -u +%FT%TZ) | $ST" >> $TW/logs/$D.log; gsutil -q cp $TW/logs/$D.log $B/results/timed_writes/${D}_12a.log || true
