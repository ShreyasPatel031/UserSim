#!/bin/bash
# Hourly store_v3 rebuild for the 48 h coverage plan (population agent). Target: published by :35 each hour.
# Sync inputs from GCS -> build into a temp dir -> publish only if check_store passes -> coverage report -> log line.
# Usage: tools/population/hourly_rebuild.sh WORK_DIR   (WORK_DIR holds raw/, salt; never committed)
set -uo pipefail
W=${1:?work dir}; R=$W/raw; B=gs://usersim-bakeoff-347838016394/usersim_sim
REPO=$(cd "$(dirname "$0")/../.." && pwd)
LOCK=$W/.rebuild.lock
exec 9>"$LOCK"; flock -n 9 || { echo "previous rebuild still running; skip"; exit 0; }
T0=$(date -u +%s); DAY=$(date -u +%F); NOW=$(date -u +%FT%TZ)
log() { echo "$(date -u +%T) $*"; }

log "sync"
mkdir -p $R/people_live/vm $R/people_live/light $R/api_comments $R/population_data
gsutil -q -m rsync -d -x '.*(_code|logs|status|heartbeat)/.*|heartbeat.*' $B/raw/ph_population/people_live/vm/ $R/people_live/vm/
gsutil -q ls $B/raw/ph_population/people_live/light/ >/dev/null 2>&1 && gsutil -q -m rsync -r -d $B/raw/ph_population/people_live/light/ $R/people_live/light/
gsutil -q -m rsync -r $B/raw/ph_population/people_live/boxbrowser/ $R/people_live/boxbrowser/ 2>/dev/null
for d in $(gsutil ls -d "$B/raw/ph_at_launch/2026-1*/api_comments/" "$B/raw/ph_at_launch/2026-1*/api_replies/" 2>/dev/null); do
  t=$(echo "$d" | sed "s#$B/raw/ph_at_launch/##; s#/\$##; s#/#_#g"); mkdir -p $R/api_comments/$t
  gsutil -q -m rsync "$d" $R/api_comments/$t/
done
gsutil -q -m rsync -r $B/raw/population_data/ $R/population_data/ 2>/dev/null
gsutil -q cp $B/raw/ph_population/people_live/have_index.jsonl $W/have_index.jsonl

log "build"
rm -rf $W/store_tmp; mkdir -p $W/store_tmp
OUT=$(cd "$REPO" && timeout 1500 python3 tools/population/store.py build $R $W/store_tmp --salt-file $W/salt 2>&1)
echo "$OUT" | grep -v '^X drops' | head -14
PASS=$(echo "$OUT" | grep -cE '^ "pass": true')
EVENTS=$(echo "$OUT" | grep -E '^ "events": ' | head -1 | grep -o '[0-9]*')
if [ "$PASS" -ge 1 ]; then
  cp $W/have_index.jsonl $W/store_tmp/
  (cd "$REPO" && python3 tools/population/report.py $W/store_tmp $DAY) > $W/store_tmp/coverage.md
  gsutil -q -m cp $W/store_tmp/events.parquet $W/store_tmp/persons.parquet $W/store_tmp/tabs.parquet $B/raw/population/store_v3/
  gsutil -q cp $W/store_tmp/coverage.md $B/raw/population/reports/$DAY/coverage.md
  [ -f $W/store_tmp/deep_list.tsv ] && gsutil -q cp $W/store_tmp/deep_list.tsv $B/raw/population/requests/deep_list_latest.tsv
  rm -rf $W/store_v3; mv $W/store_tmp $W/store_v3
  HEAD=$(grep -o 'HEADLINE.*' $W/store_v3/coverage.md | head -1); LIGHT=$(grep -o 'Light pulls.*' $W/store_v3/coverage.md | head -1)
  STATUS=published
else
  HEAD=""; LIGHT=""; STATUS=FAILED_not_published
fi
SECS=$(( $(date -u +%s) - T0 ))
python3 -c "import json,sys; print(json.dumps({'utc': sys.argv[1], 'status': sys.argv[2], 'events': sys.argv[3], 'seconds': int(sys.argv[4]), 'headline': sys.argv[5], 'light': sys.argv[6]}))" \
  "$NOW" "$STATUS" "${EVENTS:-}" "$SECS" "$HEAD" "$LIGHT" > $W/logline.json
(gsutil -q cat $B/raw/population/reports/$DAY/rebuild_log.jsonl 2>/dev/null; cat $W/logline.json) | gsutil -q cp - $B/raw/population/reports/$DAY/rebuild_log.jsonl
log "$STATUS in ${SECS}s"; cat $W/logline.json
