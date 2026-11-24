#!/bin/bash
# Nightly explain chain, self-contained for a fresh scheduled session (orchestrator EXPLAIN-OFF-SESSION, Nov 24).
# State that used to live in E5's scratchpad lives in gs://.../tmp/e5/private/explain_state/ (private): synced down at the start, up at the end.
# PH ops code is a pinned worktree (origin/claude/ph-ops-agent @ PHOPS_SHA); the bge-small model is synced from the bucket (runs offline).
#   bash explain_fresh.sh [D]        (EXPLAIN_WORK = work dir, default ~/explainwork)
set -u; B=gs://usersim-bakeoff-347838016394/usersim_sim; S=$B/tmp/e5/private/explain_state; D=${1:-$(TZ=America/Los_Angeles date +%F)}
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"; SP=${EXPLAIN_WORK:-$HOME/explainwork}; mkdir -p $SP; LOG=$SP/explain_fresh_$D.log
PHOPS_SHA=b86f582d026852fcc03b08119de5830029b2049f; DIRS="cf rb early rbundle why segments persona bp explain_past backer bkf refresh_priority explain"
exec > >(tee -a $LOG) 2>&1; echo "start $(date -u +%FT%TZ) D=$D SP=$SP"
if [ -n "${EXPLAIN_REHEARSAL:-}" ]; then export PATH="$HERE/rehearsal_bin:$PATH"; echo "REHEARSAL: all bucket writes go to usersim_sim/_rehearsal/ (reads prefer rehearsal copies)"; fi
export HF_HOME=${HF_HOME:-/tmp/hf} HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1; mkdir -p $HF_HOME/hub
gsutil -m -q rsync -r $S/hf/models--BAAI--bge-small-en-v1.5 $HF_HOME/hub/models--BAAI--bge-small-en-v1.5 || echo "WARN hf model sync"
for d in $DIRS; do mkdir -p $SP/$d; gsutil -m -q rsync -r $S/$d $SP/$d || { echo "FAIL state $d"; exit 2; }; done
if [ -n "${FRESH_PHOPS:-}" ] && [ ! -e $SP/phops ]; then ln -s $FRESH_PHOPS $SP/phops; fi
if [ ! -d $SP/phops/experiments ]; then git -C "$REPO" fetch -q origin claude/ph-ops-agent && git -C "$REPO" worktree add -f --detach $SP/phops $PHOPS_SHA -q || { echo FAIL phops; exit 2; }; fi
mkdir -p $SP/store_live; gsutil -q cp $B/raw/population/store_v3/persons.parquet $B/raw/population/store_v3/events.parquet $SP/store_live/ || { echo FAIL store; exit 2; }
(cd "$REPO/experiments" && python3 -c "from pipeline import warehouse; warehouse.table('launches', do_sync=True)" > /dev/null 2>&1)
for p in raw/daily/$D/today_0005.json results/web/why/${D}_0005.json results/shadow_readable/$D.json tmp/e5/forward_sim/$D/predictions_frozen.json; do
  for i in $(seq 1 9); do gsutil -q stat $B/$p && break; echo "waiting for $p"; sleep 600; done; done
cd "$HERE"
H25_SRC=$SP/rb/h25src python3 population_segments.py $SP/store_live $SP/cf $SP --cut $D || echo STEPFAIL0
python3 backer_arms.py $SP/store_live $SP $D || echo STEPFAIL1
python3 cohort_calibration/backer_v2_lists.py $SP/store_live $D || echo STEPFAIL1c
python3 refresh_priority.py $SP/store_live $SP $D || echo STEPFAIL1b
python3 explain_writer.py $D $SP/store_live $SP $SP/explain || echo STEPFAIL2
SEG_SP=$SP python3 persona_cards.py $SP/store_live $SP $D || echo STEPFAIL3
python3 persona_say.py $D $SP || echo STEPFAIL4
python3 expected_voters.py $SP/store_live $SP $D || echo STEPFAIL5
PAST=""; for i in 7 6 5 4 3 2 1; do d=$(date -d "$D - $i day" +%F); PAST="$PAST $d"; [ -f $SP/explain_past/$d.json ] || gsutil -q cp $B/results/web/explain/$d.json $SP/explain_past/ 2>/dev/null; done
python3 explain_after.py $SP/store_live $SP/explain_past $PAST || echo STEPFAIL6
HIST=""; d=2026-11-08; while [ "$d" \< "$D" ]; do HIST="$HIST $d"; d=$(date -d "$d + 1 day" +%F); done
python3 backer_arms_score.py $SP/store_live $SP $HIST || echo STEPFAIL7
python3 backer_forward_nightly.py $SP/store_live $SP $D 4 || echo STEPFAIL8
for d in segments persona bp explain_past backer bkf refresh_priority explain early cf; do gsutil -m -q rsync -r $SP/$d $S/$d || echo "WARN state up $d"; done
grep -c -E '"@[A-Za-z]' $SP/explain/$D.json | sed 's/^/handle_matches_in_explain=/'
gsutil -q cp $LOG $B/tmp/e5/private/explain_logs/$D.log; echo "spend tail:"; tail -3 "$HERE/spend.jsonl"
echo ALLDONE "$(date -u +%FT%TZ)"
