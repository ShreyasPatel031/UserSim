#!/bin/bash
# E5 nightly /try forward shadow job (orchestrator 23:15Z Nov 13). Run once a day after 01:00 PT (scheduled 09:17Z).
#  1. JUDGE yesterday (PT): final ranks + launch-day comments -> forward_sim (reuses the predictions frozen last night) -> forward_table.
#  2. PREDICT today (PT): forward_band (page read where a real website URL is held now) -> forward_sim FWD_PREDICT=1 (pasted path from the
#     00:05 read for every launch, page path where read) -> predictions frozen to gs://.../tmp/e5/forward_sim/<day>/predictions_frozen.json.
# Gemini only; no Product Hunt requests (pages only through the site's safe_fetch). VERCEL is unset so safe_fetch uses the proxy.
#    bash forward_nightly.sh <scratchpad> <ph-website worktree>
set -u; export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1   # Nov 18: the predict step failed trying to reach the HF hub (ConnectError); models are cached
SP=$1; WT=$2; cd "$(dirname "$0")"; OUT=reports/forward_sim/nightly; mkdir -p $OUT $SP/forward
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
# SINGLE-WRITER RULE (orchestrator 20:21Z Nov 14): the website writers below also run on the VM (bundle 12, tw.sh e5w:* jobs from the vm_writers
# tarball). Heartbeat = an "e5w:" line in the VM's own job log results/timed_writes/<day>.log for today or yesterday (PT). If present, the VM
# owns tmp/e5/website/* and this container writes nothing there; E5_CONTAINER_WRITERS=1 forces the container run (manual fallback only).
# The decision is logged and written to tmp/e5/website/writer_owner.json so anyone can see who wrote last night's files.
# today-rows fix date (deploy_today_rows.sh marker, bucket copy) -> per-day "fix pending" notes in the writers (same as tw.sh on the VM)
export TODAY_BUG_FIXED=$(gsutil cat gs://usersim-bakeoff-347838016394/usersim_sim/results/web/today_rows_fix.json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['fixed_from'])" 2>/dev/null)
BK=gs://usersim-bakeoff-347838016394/usersim_sim
vm_live() { for d in $TODAY $YDAY; do gsutil cat $BK/results/timed_writes/$d.log 2>/dev/null | grep -q "^e5w:" && return 0; done; return 1; }
if vm_live && [ "${E5_CONTAINER_WRITERS:-0}" != 1 ]; then OWNER=vm; echo "website writers: VM heartbeat found (e5w: in results/timed_writes) -> container writers skipped" >> $LOG
else OWNER=container; [ "${E5_CONTAINER_WRITERS:-0}" = 1 ] && echo "website writers: forced container run (E5_CONTAINER_WRITERS=1)" >> $LOG
  # held-team shadow column (orchestrator 00:42Z Nov 14): score yesterday, then predict today with the frozen weight
  python held_team_shadow.py score $YDAY $SP >> $LOG 2>&1
  python held_team_shadow.py predict $TODAY $SP >> $LOG 2>&1
  # website track record (orchestrator 01:02Z Nov 14): rebuild tmp/e5/website/track_record_v1.json incl. yesterday's live rows
  python track_record.py $SP >> $LOG 2>&1
  # per-launch probabilities, 00:05 (orchestrator 01:20Z Nov 14); the 03:45 file is written by the 12:07Z job
  python prob_writer.py 0005 $TODAY $SP >> $LOG 2>&1
  # running weekly / monthly boards with stated chances (orchestrator 01:28Z Nov 14), for the PT day just closed
  python period_writer.py $YDAY $SP >> $LOG 2>&1
  # period scorer (orchestrator 12:38Z Nov 14): after a week / month closes, score its boards vs the first read after the close
  [ "$(date -d $YDAY +%u)" = 7 ] && python period_score.py week $YDAY $SP >> $LOG 2>&1
  [ "$(date -d "$YDAY + 1 day" +%d)" = 01 ] && python period_score.py month $YDAY $SP >> $LOG 2>&1
fi
echo "{\"owner\": \"$OWNER\", \"checked_at\": \"$(date -u +%FT%TZ)\", \"rule\": \"VM e5w: heartbeat in results/timed_writes/<day>.log -> VM writes; else container\"}" | gsutil -q cp - $BK/tmp/e5/website/writer_owner.json || true
# arm-2 live-vs-backtest parity for yesterday (orchestrator 19:16Z Nov 14; not a website writer): message the orchestrator only on "PARITY ALERT"
bash parity_nightly.sh $SP >> $LOG 2>&1
echo "end $(date -u +%FT%TZ)" >> $LOG; tail -c 1500 $LOG
