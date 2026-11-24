#!/bin/bash
# Person-built panel (step 4b) + forward_says scoring of the previous day, self-contained for a fresh scheduled session
# (orchestrator 18:13Z Nov 24: the explain step must not depend on E5's session). Waits for the day's explain file to be complete
# (expected_voters has written who.group_mix_prior), then writes say.person_built_panel; then scores D-1 (merged + persona-only shadow)
# and uploads the scoring and the frozen truth to the bucket.   bash panel_nightly.sh [D]
set -u; B=gs://usersim-bakeoff-347838016394/usersim_sim; D=${1:-$(TZ=America/Los_Angeles date +%F)}; Y=$(date -d "$D - 1 day" +%F)
HERE="$(cd "$(dirname "$0")" && pwd)"; SIMLAB="$(dirname "$HERE")"; W=${PANEL_WORK:-$HOME/panelwork}; mkdir -p $W/explain; LOG=$W/panel_$D.log
exec > >(tee -a $LOG) 2>&1; echo "start $(date -u +%FT%TZ) D=$D"; export HF_HUB_OFFLINE=1
# PANEL_PRESTEPS=1 turns on run_forward_day (D-1) + run_refresh (D); off until the overlay re-run issue is fixed (E5 report 18:50Z Nov 24)
# reference code (claude/cool-volta-l5nuo4, fetched fresh each night) + tables through the harness build pointer (orchestrator 18:28Z Nov 24)
if [ -n "${FRESH_SIMHARNESS:-}" ]; then rm -rf $W/cv; mkdir -p $W/cv; cp -r $FRESH_SIMHARNESS/simharness $W/cv/; echo "simharness code: bundle $(cat $FRESH_SIMHARNESS/../manifest.json 2>/dev/null)"
else git -C "$SIMLAB/../.." fetch -q origin claude/cool-volta-l5nuo4; CVREV=$(git -C "$SIMLAB/../.." rev-parse FETCH_HEAD)
if [ -d $W/cv/simharness ]; then git -C $W/cv checkout -q --detach $CVREV; else git -C "$SIMLAB/../.." worktree add -f --detach $W/cv $CVREV -q; fi; echo "simharness code: $CVREV"; fi
mkdir -p $W/builds $W/forward $W/store; SYNC=${PRE_SYNC-1}
gsutil -m -q cp $B/raw/population/store_v3/persons.parquet $B/raw/population/store_v3/events.parquet $B/raw/population/store_v3/tabs.parquet $W/store/ || echo "WARN store"
mkdir -p $W/store/records; gsutil -m -q rsync -r $B/raw/population/store_v3/records $W/store/records || echo "WARN store records"
gsutil -m -q rsync -r $B/simharness/bench_v0/forward $W/forward || echo "WARN forward sync"
stamp=$(gsutil cat $B/simharness/bench_v0/builds/latest 2>/dev/null | tr -d '[:space:]')
if [ -n "$stamp" ]; then mkdir -p $W/builds/$stamp; gsutil -m -q rsync -r $B/simharness/bench_v0/builds/$stamp $W/builds/$stamp && echo "$stamp" > $W/builds/latest; fi
LY=$W/lineup_$Y.json; LD=$W/lineup_$D.json; gsutil -q cp $B/raw/daily/$Y/today_0005.json $LY; gsutil -q cp $B/raw/daily/$D/today_0005.json $LD
ST=$W/stream_$Y.jsonl; gsutil -q cp $B/raw/ph_at_launch/$Y/live/comments_ts.jsonl $ST 2>/dev/null   # platform ids/handles: used only by run_forward_day, deleted below
if [ -n "${PANEL_PRESTEPS:-}" ] && [ -s $ST ] && [ -n "$stamp" ]; then (cd $W/cv && timeout 1200 python3 -m simharness.run_forward_day --day $Y --bench $W/builds --forward-root $W/forward --stream $ST --lineup $LY --persons $W/store/persons.parquet ${SYNC:+--sync $B/simharness/bench_v0/forward}) || echo "WARN run_forward_day $Y failed"; fi
rm -f $ST
[ -n "${PANEL_PRESTEPS:-}" ] && [ -n "$stamp" ] && (cd $W/cv && timeout 1800 python3 -m simharness.run_refresh --store $W/store --out $W/builds --forward-root $W/forward --day $D --lineup $LD ${SYNC:+--sync $B/simharness/bench_v0/builds}) || echo "WARN run_refresh $D failed or checks did not pass: using the pointer's current build"
stamp=$(cat $W/builds/latest 2>/dev/null | tr -d '[:space:]')
if [ -n "$stamp" ] && [ -f $W/builds/$stamp/people.parquet ]; then BENCHDIR=$W/builds; SRC="$B/simharness/bench_v0/builds/$stamp"
else mkdir -p $W/bench_v0/data; gsutil -m -q rsync -r $B/simharness/bench_v0/data $W/bench_v0/data; BENCHDIR=$W/bench_v0/data; SRC="$B/simharness/bench_v0/data (fallback, Nov 23 build)"; fi
echo "tables: $SRC"
[ -n "${PANEL_PRE_ONLY:-}" ] && { echo "pre-steps only: stop"; exit 0; }
for i in $(seq 1 30); do
  ok=$(gsutil cat $B/results/web/explain/$D.json 2>/dev/null | python3 -c "import json,sys; J=json.load(sys.stdin).get('launches',{}); print(int(bool(J) and all('group_mix_prior' in (v.get('who') or {}) for v in J.values())))" 2>/dev/null)
  [ "$ok" = "1" ] && break; echo "waiting for the explain file ($i)"; sleep 120; done
[ "$ok" = "1" ] || echo "explain file not complete after 60 min: running anyway"
cd "$HERE" && PANEL_TABLES="$SRC" PANEL_BENCH="$BENCHDIR" python3 person_panel.py $D $W ${PANEL_ARGS:-}; R4=$?
# score D-1 with the frozen truth shared through the bucket
mkdir -p "$SIMLAB/reports/forward_sim/truth"; gsutil -m -q cp "$B/results/calibration/forward_says/truth/truth_$Y.v*.json" "$SIMLAB/reports/forward_sim/truth/" 2>/dev/null
cd "$SIMLAB" && python3 forward_says.py $Y $W > $W/fs_$Y.log 2>&1; RF=$?
gsutil -m -q cp "$SIMLAB/reports/forward_sim/truth/truth_$Y.v*.json" $B/results/calibration/forward_says/truth/ 2>/dev/null
gsutil -m -q cp "$SIMLAB/reports/forward_sim/forward_says_$Y.v*.json" $B/results/calibration/forward_says/ 2>/dev/null
gsutil -q cp $LOG $B/tmp/e5/private/panel_logs/$D.log
echo "end $(date -u +%FT%TZ) panel=$R4 score_$Y=$RF"
