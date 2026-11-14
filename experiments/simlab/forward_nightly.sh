#!/bin/bash
# E5 nightly /try forward shadow job (orchestrator 23:15Z Nov 13). Run once a day after 01:00 PT (scheduled 09:17Z).
#  1. JUDGE yesterday (PT): final ranks + launch-day comments -> forward_sim (reuses the predictions frozen last night) -> forward_table.
#  2. PREDICT today (PT): forward_band (page read where a real website URL is held now) -> forward_sim FWD_PREDICT=1 (pasted path from the
#     00:05 read for every launch, page path where read) -> predictions frozen to gs://.../tmp/e5/forward_sim/<day>/predictions_frozen.json.
# Gemini only; no Product Hunt requests (pages only through the site's safe_fetch). VERCEL is unset so safe_fetch uses the proxy.
#    bash forward_nightly.sh <scratchpad> <ph-website worktree>
set -u; SP=$1; WT=$2; cd "$(dirname "$0")"; OUT=reports/forward_sim/nightly; mkdir -p $OUT $SP/forward
BA=gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/forward_assets
for f in frozen_run1.pkl frozen_run2.pkl; do [ -f $SP/forward/$f ] || gsutil -q cp $BA/$f $SP/forward/; done
[ -f $SP/clean_nosite.parquet ] || gsutil -q cp $BA/clean_nosite.parquet $SP/
cd /home/user/UserSim/experiments && python -c "from pipeline import warehouse; warehouse.table(\"launches\", do_sync=True)" > /dev/null 2>&1; cd - > /dev/null
TODAY=$(TZ=America/Los_Angeles date +%F); YDAY=$(TZ=America/Los_Angeles date -d yesterday +%F); LOG=$SP/nightly_$TODAY.log
echo "start $(date -u +%FT%TZ) today=$TODAY yday=$YDAY" >> $LOG
if gsutil -q stat gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/forward_sim/$YDAY/predictions_frozen.json; then
  env -u VERCEL python forward_sim.py $YDAY $WT $SP $OUT >> $LOG 2>&1 && python forward_table.py $OUT >> $LOG 2>&1
else echo "no frozen predictions for $YDAY: nothing to judge" >> $LOG; fi
env -u VERCEL python forward_band.py $TODAY $SP $WT >> $LOG 2>&1
FWD_PREDICT=1 env -u VERCEL python forward_sim.py $TODAY $WT $SP $OUT >> $LOG 2>&1
# held-team shadow column (orchestrator 00:42Z Nov 14): score yesterday, then predict today with the frozen weight
python held_team_shadow.py score $YDAY $SP >> $LOG 2>&1
python held_team_shadow.py predict $TODAY $SP >> $LOG 2>&1
echo "end $(date -u +%FT%TZ)" >> $LOG; tail -c 1500 $LOG
