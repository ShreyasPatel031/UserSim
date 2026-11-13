#!/bin/bash
# Nightly logged input (orchestrator 05:00Z Nov 13): E5's follow_shadow.py (claude/person-model-v2 a754cb28) on the day's 00:05 line-up.
# Run after the 00:05 read exists (any timed run after 01:00 PT). No Product Hunt requests. Ids and counts only; the salt is read by
# the script, never printed. Writes gs://.../tmp/e5/follow_shadow/shadow_<D>.jsonl unless it already exists.
# usage: bash e5_follow_run.sh <YYYY-MM-DD> <work dir holding follow_shadow.py, store/, s/salt>
set -euo pipefail
D="$1"; W="$2"; B=gs://usersim-bakeoff-347838016394/usersim_sim
OUT="$B/tmp/e5/follow_shadow/shadow_$D.jsonl"
if gsutil -q stat "$OUT"; then echo "exists $OUT"; exit 0; fi
gsutil -q stat "$B/raw/daily/$D/today_0005.json" || { echo "no 00:05 read for $D"; exit 1; }
mkdir -p "$W/store" "$W/s"
# store (orchestrator via E5 06:09Z Nov 13): E5's merged store until the population agent publishes the official merged one
STORE="${E5_STORE:-$B/tmp/e5/merged_store_20261113}"; SD="$W/store_$(basename "$STORE")"; mkdir -p "$SD"
gsutil -q -m cp -n "$STORE/events.parquet" "$STORE/persons.parquet" "$SD/"
[ -s "$W/s/salt" ] || gsutil -q cp "$B/raw/population/_salt" "$W/s/salt"
python3 -I "$W/follow_shadow.py" "$B/raw/daily/$D/today_0005.json" "$D" "$SD" "$W/s" "$W/out_$D.jsonl"
echo "{\"day\": \"$D\", \"store\": \"$STORE\", \"written_at\": \"$(date -u +%FT%TZ)\"}" | gsutil -q cp - "$B/tmp/e5/follow_shadow/shadow_$D.store.json"
gsutil -q cp "$W/out_$D.jsonl" "$OUT"; echo "wrote $OUT"
