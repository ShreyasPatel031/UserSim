#!/bin/bash
# Bundle 12a runner on usersim-pipeline: rec (extra recorder read) | midnight | prereveal. One flock per job. A write that already exists with
# no fallback is skipped (so the second scheduled slot is a retry only). Each attempt is retried once after 60 s; exit code is the final rc
# (review B5). One log line per run to /home/agent/w/tw12a/logs/<day>.log (copied to gs://.../results/timed_writes/<day>_12a.log) and a
# status file gs://.../results/timed_writes/status_12a_<job>.json {job, day, rc, written_at, due_pt} for the freshness audit.
set -uo pipefail
J=${1:?job}; TW=/home/agent/w/tw12a; B=gs://usersim-bakeoff-347838016394/usersim_sim
export PATH=/opt/exp/bin:$PATH TZ=America/Los_Angeles; D=$(date +%F); mkdir -p $TW/logs $TW/locks
exec 8>$TW/locks/$J.lock
flock -n 8 || { echo "$J $D skipped: locked (an earlier attempt is still running) $(date -u +%FT%TZ)" >> $TW/logs/$D.log; exit 0; }
# a retry slot (any midnight slot after the first, 00:20 PT) does not wait for the parquet: a missing parquet means none_available now and
# the next slot tries again, so an attempt never holds the lock across the next slot
FIRST=0; [ "$J" = midnight ] && [ "$(date +%H%M)" -lt 0030 ] && FIRST=1
declare -A DUE=([midnight]="00:25" [prereveal]="03:50" [rec]="03:45")
# done = written with a model and fallback_used null; none_available / stale_read / any fallback is NOT done, so the next slot (00:35, 01:30;
# 03:52) rewrites it once the input lands (orchestrator 12:36Z Nov 14)
done_ok() { gsutil cat $B/results/web/predictions/${D}_$1.json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('fallback_used') is None and d.get('model') else 1)" 2>/dev/null; }
attempt() {
  case "$J" in
  rec)
    export PH_TOKEN=$(python3 -c "import json; print(json.load(open('/var/lib/usersim/discovery_keys.json'))['PH_TOKEN'])")
    OUT=$(cd /home/agent/w/experiments && timeout 300 python3 $TW/recorder_extra.py 2>&1); RC=$?; unset PH_TOKEN;;
  midnight)
    [ $FIRST = 1 ] && for i in $(seq 1 26); do [ -f /home/agent/w/experiments/ph_predict/results/forecast_$D.parquet ] && break; sleep 30; done
    OUT=$(timeout 300 python3 $TW/two_predictions.py midnight $D 2>&1); RC=$?;;
  prereveal)
    OUT=$(timeout 300 python3 $TW/two_predictions.py prereveal $D 2>&1); RC=$?;;
  *) OUT="unknown job"; RC=64;;
  esac
}
if [ "$J" = midnight ] && done_ok 0005; then echo "$J $D skipped (already written, no fallback) $(date -u +%FT%TZ)" >> $TW/logs/$D.log; exit 0; fi
if [ "$J" = prereveal ] && done_ok prereveal; then echo "$J $D skipped (already written, no fallback) $(date -u +%FT%TZ)" >> $TW/logs/$D.log; exit 0; fi
attempt; FIRST=0; [ $RC -ne 0 ] && [ $RC -ne 64 ] && { sleep 60; attempt; }
LAST=$(echo "$OUT" | tail -1 | cut -c1-300)
echo "$J $D rc=$RC written at $(date -u +%FT%TZ) | $LAST" >> $TW/logs/$D.log
gsutil -q cp $TW/logs/$D.log $B/results/timed_writes/${D}_12a.log || true
echo "{\"job\": \"$J\", \"day\": \"$D\", \"rc\": $RC, \"written_at\": \"$(date -u +%FT%TZ)\", \"due_pt\": \"${DUE[$J]:-}\"}" | gsutil -q cp - $B/results/timed_writes/status_12a_$J.json || true
exit $RC
