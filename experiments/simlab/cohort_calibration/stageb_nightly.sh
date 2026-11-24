#!/bin/bash
# SIM-RERANK-1 Stage B nightly, self-contained (orchestrator 13:30Z Nov 24: the freeze must not depend on E5's session being awake).
# Runs in a fresh cloud session started by a scheduled task. Pulls inputs from the bucket, runs arm v2 (pick-k) then v1, freezes before 03:45 PT.
#   bash experiments/simlab/cohort_calibration/stageb_nightly.sh [D]
set -u; B=gs://usersim-bakeoff-347838016394/usersim_sim; D=${1:-$(TZ=America/Los_Angeles date +%F)}
HERE="$(cd "$(dirname "$0")" && pwd)"; W=${STAGEB_WORK:-$HOME/stageb}; mkdir -p $W/store_live $W/kinds $W/forward; LOG=$W/stageb_$D.log
PY=python3; python3 -c "import pandas, sklearn" 2>/dev/null || PY="$HERE/../../../.venv/bin/python"
exec > >(tee -a $LOG) 2>&1; echo "start $(date -u +%FT%TZ) D=$D"
export HF_HUB_OFFLINE=1 SIM_SP=$W
gsutil -q cp $B/raw/population/store_v3/persons.parquet $B/raw/population/store_v3/events.parquet $W/store_live/ || { echo FAIL store; exit 2; }
gsutil -q cp $B/tmp/e5/private/stageb_bundle/tracked_comments.parquet $W/kinds/ || { echo FAIL bundle; exit 2; }
(cd "$HERE/../.." && $PY -c "from pipeline import warehouse; warehouse.table('launches', do_sync=True)" > /dev/null 2>&1)
for i in $(seq 1 18); do gsutil -q stat $B/tmp/e5/private/backer_pred_v2/$D.parquet && break; [ $i -eq 6 ] && (cd "$HERE" && $PY backer_v2_lists.py $W/store_live $D); sleep 60; done
for i in $(seq 1 20); do gsutil -q stat $B/results/structural/$D/shortlist.json && break; [ "$(date -u +%H%M)" \> "1105" ] && { echo "shortlist missing: 00:05 fallback"; break; }; sleep 60; done
cd "$HERE" && $PY rerank_b2.py $W/store_live $W $D ${STAGEB_DRY:+--dry}; R2=$?
$PY rerank_b.py $W/store_live $W $D ${STAGEB_DRY:+--dry}; R1=$?
[ -z "${STAGEB_DRY:-}" ] && gsutil -q cp $LOG $B/tmp/e5/private/stageb_logs/$D.log
echo "end $(date -u +%FT%TZ) v2=$R2 v1=$R1"
