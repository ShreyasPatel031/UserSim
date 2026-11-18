#!/bin/bash
# Nightly logged input #2 (orchestrator GO via E5, 10:39Z Nov 13): E5's team_shadow.py (claude/person-model-v2 4e4dd4e9 since 19:50Z Nov 13: + n_team_estab) on the
# day's 00:05 line-up. No LLM, no Product Hunt requests; ids and counts only; the salt is read by the script, never printed.
# Needs a worktree of that commit (it imports experiments/pipeline/warehouse.py). Skips if E5's file for <D> already exists.
# usage: bash e5_team_run.sh <YYYY-MM-DD> <work dir holding s/salt> <worktree of aed7f324>
set -euo pipefail
D="$1"; W="$2"; WT="$3"; B=gs://usersim-bakeoff-347838016394/usersim_sim
OUT="$B/tmp/e5/team_shadow/team_shadow_$D.jsonl"
# RELOG=1: re-run after the 10:17 PT store merge only to log the true pulled-by-01:00 count (no upload, existing file kept)
if [ "${RELOG:-0}" != 1 ] && gsutil -q stat "$OUT"; then echo "exists $OUT"; exit 0; fi
gsutil -q stat "$B/raw/daily/$D/today_0005.json" || { echo "no 00:05 read for $D"; exit 1; }
# official merged store (orchestrator 11:49Z Nov 13); it is rewritten in place, so the local copy is keyed by events.parquet generation
STORE="${E5_STORE:-$B/raw/population/store_v3}"; GEN=$(gsutil stat "$STORE/events.parquet" | awk '/Generation:/{print $2}'); SD="$W/store_$(basename "$STORE")_$GEN"; mkdir -p "$SD" "$W/s"
gsutil -q -m cp -n "$STORE/events.parquet" "$STORE/persons.parquet" "$STORE/tabs.parquet" "$SD/"
[ -s "$W/s/salt" ] || gsutil -q cp "$B/raw/population/_salt" "$W/s/salt"
HERE_="$(cd "$(dirname "$0")" && pwd)"; cd "$WT/experiments/simlab"
python3 team_shadow.py "$B/raw/daily/$D/today_0005.json" "$D" "$SD" "$W/s" "$W/team_shadow_$D.jsonl" 2>&1 | tee "$W/team_shadow_$D.log"
# nightly log (orchestrator via E5 14:54Z Nov 13): "team members pulled before 01:00 PT X of Y", with the store generation used
LINE=$(grep -o "pulled before 01:00 PT [0-9]* of [0-9]*" "$W/team_shadow_$D.log" | tail -1 || true)
X=$(echo "$LINE" | awk '{print $(NF-2)}'); Y=$(echo "$LINE" | awk '{print $NF}')
echo "{\"day\": \"$D\", \"run_at\": \"$(date -u +%FT%TZ)\", \"relog\": ${RELOG:-0}, \"store_generation\": \"$GEN\", \"team_pulled_before_0100\": ${X:-null}, \"team_total\": ${Y:-null}}" >> "$HERE_/results/team_pulled_0100.jsonl"
if [ "${RELOG:-0}" = 1 ]; then echo "relog only: $LINE"; exit 0; fi
gsutil -q cp "$W/team_shadow_$D.jsonl" "$OUT"; echo "wrote $OUT"
