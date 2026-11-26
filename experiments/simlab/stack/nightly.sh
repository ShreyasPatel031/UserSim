#!/bin/bash
# STACK-1b forward backer line, nightly (PREREG addendum 14; ledger STACK-FWD-1). Fresh session via fresh/bootstrap.sh stack [D].
# Starts ~01:50 PT once D's 00:05 line-up file exists; freezes tmp/e5/private/backer_pred_stack/<D>.parquet before 03:30 PT.
set -u; B=gs://usersim-bakeoff-347838016394/usersim_sim; D=${1:-$(TZ=America/Los_Angeles date +%F)}
HERE="$(cd "$(dirname "$0")" && pwd)"; W=${PU_WORK:-/tmp/pu}; mkdir -p $W; LOG=$W/stack_$D.log; exec > >(tee -a $LOG) 2>&1
echo "start $(date -u +%FT%TZ) D=$D"
until gsutil -q stat $B/raw/daily/$D/today_0005.json; do
  [ "$(date -u +%FT%TZ)" \> "$(TZ=UTC date -d "TZ=\"America/Los_Angeles\" $D 02:30" +%FT%TZ)" ] && { echo "MISSING today_0005 by 02:30 PT"; break; }; sleep 120; done
cd "$HERE" && env -u VERCEL python3 stack_nightly.py $D || echo "FAIL stack $D"
gsutil -q cp $LOG $B/tmp/e5/private/stack/logs/$D.log; echo ALLDONE "$(date -u +%FT%TZ)"
