#!/bin/bash
# PRODUCT-USE-1 nightly (PREREG addendum 11), fresh scheduled session via fresh/bootstrap.sh product_use [D].
# D (PT launch day): wait for the structural shortlist (01:20 PT), choose users from the panel selection (PREREG 11c), build the frozen line-up, run the
# homepage control and the product-use sessions with no new session after 03:25 PT, freeze outputs; then score D-1 (truth is in by now).
set -u; B=gs://usersim-bakeoff-347838016394/usersim_sim; D=${1:-$(TZ=America/Los_Angeles date +%F)}; Y=$(date -d "$D - 1 day" +%F)
HERE="$(cd "$(dirname "$0")" && pwd)"; W=${PU_WORK:-/tmp/pu}; mkdir -p $W; LOG=$W/product_use_$D.log; exec > >(tee -a $LOG) 2>&1
echo "start $(date -u +%FT%TZ) D=$D"
export HF_HOME=${HF_HOME:-/tmp/hf} HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1; mkdir -p $HF_HOME/hub/models--BAAI--bge-small-en-v1.5
gsutil -m -q rsync -r $B/tmp/e5/private/explain_state/hf/models--BAAI--bge-small-en-v1.5 $HF_HOME/hub/models--BAAI--bge-small-en-v1.5 || echo "WARN hf model sync"
FREEZE=$(TZ=UTC date -d "TZ=\"America/Los_Angeles\" $D 03:25" +%FT%TZ)
for p in results/structural/$D/shortlist.json; do
  until gsutil -q stat $B/$p; do [ "$(date -u +%FT%TZ)" \> "$(TZ=UTC date -d "TZ=\"America/Los_Angeles\" $D 03:00" +%FT%TZ)" ] && { echo "MISSING $p by 03:00 PT"; break; }; echo "waiting for $p"; sleep 300; done; done
cd "$HERE"; REH=""; [ "$D" \< "${PU_FIRST_DAY:-2026-11-26}" ] && { REH="--rehearsal"; echo "DRESS REHEARSAL (before the first frozen night): outputs under _rehearsal/, never scored"; }
env -u VERCEL python3 lineup.py $D --n 15 $REH || { echo "FAIL lineup"; }
env -u VERCEL python3 control_homepage.py $D $REH || echo "WARN homepage control"
PU_TOKEN_FROM_SECRET=1 PU_DEADLINE_UTC=$FREEZE env -u VERCEL python3 runner.py $D --par ${PU_PAR:-8} --max-usd ${PU_MAX_USD:-14} --max-launches ${PU_MAXL:-15} $REH || echo "FAIL runner"
# score yesterday (forward only; Nov 24 rehearsal is never scored)
if gsutil -q stat $B/results/calibration/$Y/product_use/outputs.json; then
  python3 score.py $Y $W || echo "WARN score $Y"; python3 review_cal.py $Y || echo "WARN review_cal $Y"; fi
grep -c -E '"@[A-Za-z]' $W/$D/outputs.json 2>/dev/null | sed 's/^/handle_matches=/'
gsutil -q cp $LOG $B/tmp/e5/private/product_use/logs/$D.log; echo ALLDONE "$(date -u +%FT%TZ)"
