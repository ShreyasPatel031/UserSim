#!/bin/bash
# Person-built panel (step 4b) + forward_says scoring of the previous day, self-contained for a fresh scheduled session
# (orchestrator 18:13Z Nov 24: the explain step must not depend on E5's session). Waits for the day's explain file to be complete
# (expected_voters has written who.group_mix_prior), then writes say.person_built_panel; then scores D-1 (merged + persona-only shadow)
# and uploads the scoring and the frozen truth to the bucket.   bash panel_nightly.sh [D]
set -u; B=gs://usersim-bakeoff-347838016394/usersim_sim; D=${1:-$(TZ=America/Los_Angeles date +%F)}; Y=$(date -d "$D - 1 day" +%F)
HERE="$(cd "$(dirname "$0")" && pwd)"; SIMLAB="$(dirname "$HERE")"; W=${PANEL_WORK:-$HOME/panelwork}; mkdir -p $W/explain $W/bench_v0/data; LOG=$W/panel_$D.log
exec > >(tee -a $LOG) 2>&1; echo "start $(date -u +%FT%TZ) D=$D"; export HF_HUB_OFFLINE=1
# reference selection code + tables: the harness 'latest' tables when the refresh runner exists, else the Nov 23 bench_v0 tables
if [ ! -d $W/cv/simharness ]; then git -C "$SIMLAB/../.." fetch -q origin claude/cool-volta-l5nuo4 && git -C "$SIMLAB/../.." worktree add -f --detach $W/cv FETCH_HEAD -q; fi
TB=$(gsutil cat $B/simharness/bench_v0/latest 2>/dev/null | tr -d '[:space:]'); SRC=${TB:-$B/simharness/bench_v0/data}
gsutil -m -q rsync -r $SRC $W/bench_v0/data && echo "tables: $SRC" || { echo FAIL tables; exit 2; }
for i in $(seq 1 30); do
  ok=$(gsutil cat $B/results/web/explain/$D.json 2>/dev/null | python3 -c "import json,sys; J=json.load(sys.stdin).get('launches',{}); print(int(bool(J) and all('group_mix_prior' in (v.get('who') or {}) for v in J.values())))" 2>/dev/null)
  [ "$ok" = "1" ] && break; echo "waiting for the explain file ($i)"; sleep 120; done
[ "$ok" = "1" ] || echo "explain file not complete after 60 min: running anyway"
cd "$HERE" && PANEL_TABLES="$SRC" python3 person_panel.py $D $W ${PANEL_ARGS:-}; R4=$?
# score D-1 with the frozen truth shared through the bucket
mkdir -p "$SIMLAB/reports/forward_sim/truth"; gsutil -m -q cp "$B/results/calibration/forward_says/truth/truth_$Y.v*.json" "$SIMLAB/reports/forward_sim/truth/" 2>/dev/null
cd "$SIMLAB" && python3 forward_says.py $Y $W > $W/fs_$Y.log 2>&1; RF=$?
gsutil -m -q cp "$SIMLAB/reports/forward_sim/truth/truth_$Y.v*.json" $B/results/calibration/forward_says/truth/ 2>/dev/null
gsutil -m -q cp "$SIMLAB/reports/forward_sim/forward_says_$Y.v*.json" $B/results/calibration/forward_says/ 2>/dev/null
gsutil -q cp $LOG $B/tmp/e5/private/panel_logs/$D.log
echo "end $(date -u +%FT%TZ) panel=$R4 score_$Y=$RF"
