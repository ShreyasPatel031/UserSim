#!/bin/bash
# Bundle 12: timed writes on usersim-pipeline (cron, no Claude session needed). One job per call; every job is idempotent (skips when its
# bucket output exists, FORCE=1 rewrites), read-only for the deployed pipeline (own code tree, own results dir, own warehouse cache),
# makes NO Product Hunt / external API requests (bucket reads + local CPU only; Gemini is not called), and logs one line
# "<job> <day> written at <UTC> | inputs: <present/missing> | <status>" to $TW/logs/<day>.log, copied to gs://.../results/timed_writes/<day>.log.
# usage: tw.sh <job> [YYYY-MM-DD]   (day defaults to today's Pacific day; jobs listed in tw.cron and README.md)
set -uo pipefail
JOB="${1:?job}"; TW=/home/agent/w/tw; X=$TW/experiments; P=$X/ph_predict; B=gs://usersim-bakeoff-347838016394/usersim_sim
export PATH=/opt/exp/bin:$PATH TZ=America/Los_Angeles USERSIM_CACHE=$TW/cache TMPDIR=$TW/tmp LGB_THREADS=${LGB_THREADS:-2} MPLBACKEND=Agg
export CF_WORK=$TW/cmt LLM_PROVIDER=gemini SKIP_CLAUDE=1
unset PH_TOKEN   # never inherited: these jobs make no Product Hunt requests
D="${2:-$(date +%F)}"; Y=$(date -d "$D -1 day" +%F); DOW=$(date -d "$D" +%u)
mkdir -p $TW/logs $TW/locks $TW/tmp $TW/cache $TW/cmt
exec 8>$TW/locks/$JOB.lock; flock -n 8 || { echo "$JOB already running"; exit 0; }
LOG=$TW/logs/$D.log; IN=""; ST=""
has() { gsutil -q stat "$1" 2>/dev/null; }
need() { if has "$1"; then IN="$IN ${2}:present"; return 0; else IN="$IN ${2}:missing"; return 1; fi; }
waitfor() { local t=0; until has "$1"; do [ $t -ge "${2:-1200}" ] && return 1; sleep 30; t=$((t + 30)); done; }
logline() { echo "$JOB $D written at $(date -u +%FT%TZ) | inputs:${IN:- none} | ${ST:-ok}" >> $LOG; gsutil -q cp $LOG $B/results/timed_writes/$D.log || true; }
nicep() { nice -n 19 ionice -c3 python3 "$@"; }
sync_wh() { gsutil -q -m rsync -r $B/tables $USERSIM_CACHE >/dev/null 2>&1 || true; }
inwindow() { H=$(date +%H%M); [ "$H" -ge 0005 ] && [ "$H" -lt 0100 ]; }
FC=$B/raw/daily/$D/forecast_$D.parquet
cd $P
case "$JOB" in
P030|P0|P1|P2|P3|P345|P4)
  OUT=$B/results/early_forecast/${D}_$JOB.json
  if [ "${FORCE:-0}" != 1 ] && has $OUT; then ST="exists"; logline; exit 0; fi
  waitfor $FC 1500 && IN=" forecast_parquet:present" || IN=" forecast_parquet:missing"
  # P030 / P0 publish mrep / hr_clean from the clean shadow: wait for it (tw.sh shadow_clean, 00:20 PT) up to 00:55 PT
  if [ "$JOB" = P030 ] || [ "$JOB" = P0 ]; then waitfor $B/results/shadow_makerfix/$D.json 1200 || true; fi
  need $B/results/shadow_makerfix/$D.json shadow_clean; need $B/raw/ph_at_launch/$D/live/comments_ts.jsonl comments_ts
  [ "$JOB" = P030 ] && { need $B/results/shadow_h25/$D.json shadow_h25; need $B/results/shadow_readable/$D.json shadow_readable; }
  sync_wh; ST=$(nicep comment_forecast.py live $D $JOB 2>&1 | tail -1 | cut -c1-300); logline
  bash $0 web_forecast "$D"; bash $0 scoreboard "$D";;
shadow_clean)   # 00:20 PT: the pipeline's forecast parquet marks launches + forecast done; read-only, nice 19, no API
  OUT=$B/results/shadow_makerfix/$D.json
  if [ "${FORCE:-0}" != 1 ] && has $OUT; then ST="exists"; logline; exit 0; fi
  waitfor $FC 1800 && IN=" forecast_parquet:present" || { IN=" forecast_parquet:missing"; ST="not run"; logline; exit 1; }
  ST=$(TW_EARLY=1 nicep makerfix_shadow.py $D 2>&1 | tail -1 | cut -c1-300)
  [ -f results/shadow_makerfix/$D.json ] && gsutil -q cp results/shadow_makerfix/$D.json $OUT; logline
  bash $0 conf_live "$D";;
conf_live)
  if [ "${FORCE:-0}" != 1 ] && has $B/results/web/confidence/$D.json; then ST="exists"; logline; exit 0; fi
  need $B/results/shadow_makerfix/$D.json shadow_clean && ST=$(nicep conf_live.py $D 2>&1 | tail -1 | cut -c1-300); logline;;
shadow_h25)     # 01:05 PT (outside the window)
  OUT=$B/results/shadow_h25/$D.json; if [ "${FORCE:-0}" != 1 ] && has $OUT; then ST="exists"; logline; exit 0; fi
  need $FC forecast_parquet
  ST=$(cd /home/agent/w/experiments/ph_predict && PYTHONPATH=/home/agent/w/mk:.:$TW/h25 H25_SRC=/home/agent/w/ph_history/2025 nice -n 19 ionice -c3 python3 $TW/h25/h25_shadow.py $D 2>&1 | tail -1 | cut -c1-300)
  f=/home/agent/w/experiments/ph_predict/results/shadow_h25/$D.json; [ -f $f ] && gsutil -q cp $f $OUT; logline;;
shadow_readable)
  OUT=$B/results/shadow_readable/$D.json; if [ "${FORCE:-0}" != 1 ] && has $OUT; then ST="exists"; logline; exit 0; fi
  need $FC forecast_parquet
  ST=$(cd /home/agent/w/experiments/ph_predict && PYTHONPATH=/home/agent/w/mk:. nice -n 19 ionice -c3 python3 $TW/h25/readable_shadow.py $D 2>&1 | tail -1 | cut -c1-300)
  f=/home/agent/w/experiments/ph_predict/results/shadow_readable/$D.json; [ -f $f ] && gsutil -q cp $f $OUT; logline;;
e5)             # E5 follow + team shadow (salted ids / counts only; the salt is read by E5's scripts, never printed)
  need $B/raw/daily/$D/today_0005.json today_0005
  ST=$(bash $P/e5_follow_run.sh $D $TW/e5/e5f 2>&1 | tail -2 | tr '\n' ' ' | cut -c1-300); logline;;
why)            # forecast-side why file (E5 why_writer at the pin in why_run.sh), then drivers and top-3 confidence
  need $B/raw/population/store_v3/events.parquet store_v3
  ST=$(bash $P/why_run.sh forecast $D $TW/e5/why $TW/e5/e5why 2>&1 | tail -1 | cut -c1-200); logline
  bash $0 why_drivers "$D";;
why_drivers)
  need $B/results/web/why/${D}_0005.json why; need $B/results/shadow_readable/$D.json shadow_readable; need $B/results/early_forecast/${D}_P030.json P030
  ST=$(nicep why_drivers.py $D 2>&1 | tail -1 | cut -c1-200); logline
  bash $0 conf_top3 "$D";;
conf_top3)
  if [ "${FORCE:-0}" != 1 ] && has $B/results/web/confidence_top3_shadow/$D.json; then ST="exists"; logline; exit 0; fi
  need $FC forecast_parquet && ST=$(nicep conf_top3_shadow.py $D 2>&1 | tail -1 | cut -c1-200); logline;;
why_after)      # 10:05 PT: yesterday's after-file, after the ~09:00 PT store merge; then the true team-pulled count (no upload)
  ST=$(bash $P/why_run.sh after $Y $TW/e5/why $TW/e5/e5why 2>&1 | tail -1 | cut -c1-200); logline
  RELOG=1 bash $P/e5_team_run.sh $Y $TW/e5/e5f $TW/e5/e5wt > /dev/null 2>&1 || true
  gsutil -q cp $P/results/team_pulled_0100.jsonl $B/results/timed_writes/team_pulled_0100.jsonl || true;;
R0|R0q|R0h|R1|R2|R4|C05|C06|C12|C16)
  OUT=$B/results/early_forecast/${D}_$JOB.json; if [ "${FORCE:-0}" != 1 ] && has $OUT; then ST="exists"; logline; exit 0; fi
  need $B/raw/ph_at_launch/$D/live/coverage_ts.jsonl live_capture; sync_wh
  ST=$(nicep early_forecast.py live $D $JOB votes 2>&1 | tail -1 | cut -c1-300)
  [ -f results/early_forecast/${D}_$JOB.json ] && gsutil -q cp results/early_forecast/${D}_$JOB.json $OUT
  [ -f results/web/lock/$D.json ] && gsutil -q cp results/web/lock/$D.json $B/results/web/lock/$D.json; logline
  [ "$JOB" = R4 ] && bash $0 weekly_r4 "$D"; bash $0 scoreboard "$D";;
V05|V08|V10|V12)
  OUT=$B/results/velocity_shadow/${D}_$JOB.json; if [ "${FORCE:-0}" != 1 ] && has $OUT; then ST="exists"; logline; exit 0; fi
  sync_wh; ST=$(nicep velocity_shadow.py live $D $JOB 2>&1 | tail -1 | cut -c1-300); logline;;
dayend)         # 01:10 PT: yesterday's weekly + monthly day-end reads, then the running ranks (after the pipeline's ranks step)
  M=$(date -d "$Y -$(( $(date -d $Y +%u) - 1 )) days" +%F); YM=${Y:0:7}
  has $B/results/weekly_live/${M}_${Y}_dayend.json || nicep weekly_live.py dayend $Y > /dev/null 2>&1
  has $B/results/monthly_live/${YM}_${Y}_dayend.json || nicep monthly_live.py dayend $Y > /dev/null 2>&1
  has $B/results/weekly_live/${M}_${Y}_running.json || nicep weekly_live.py running $Y > /dev/null 2>&1
  has $B/results/monthly_live/${YM}_${Y}_running.json || nicep monthly_live.py running $Y > /dev/null 2>&1
  need $B/results/weekly_live/${M}_${Y}_dayend.json weekly_dayend; need $B/results/monthly_live/${YM}_${Y}_dayend.json monthly_dayend
  need $B/results/weekly_live/${M}_${Y}_running.json weekly_running; need $B/results/monthly_live/${YM}_${Y}_running.json monthly_running; logline;;
weekly_est)
  [ "$DOW" = 1 ] && { ST="monday: skipped"; logline; exit 0; }
  ST=$(nicep weekly_live.py est $D 2>&1 | tail -1 | cut -c1-200); logline;;
weekly_r4) ST=$(nicep weekly_live.py r4 $D 2>&1 | tail -1 | cut -c1-200); logline;;
daily_scores)   # 08:10 PT: makerfix score, confidence score; Mondays weekly score + growth fit; 1st of month monthly score
  nicep makerfix_score.py > /dev/null 2>&1; nicep conf_live.py score > /dev/null 2>&1
  [ "$DOW" = 1 ] && { nicep weekly_live.py score > /dev/null 2>&1; nicep growth.py fit > /dev/null 2>&1; }
  [ "${D:8:2}" = 01 ] && nicep monthly_live.py score > /dev/null 2>&1
  for f in results/web/confidence_scoreboard.json results/growth.json; do [ -f $f ] && gsutil -q cp $f $B/results/timed_writes/$(basename $f); done
  ST="scores run"; logline;;
web_forecast)
  inwindow && { ST="inside 00:05-01:00 PT: deferred to the 01:10 run"; logline; exit 0; }
  sync_wh; ST=$(nicep web_forecast_0005.py 2>&1 | tail -1 | cut -c1-200); logline;;
scoreboard)
  inwindow && { ST="inside 00:05-01:00 PT: deferred"; logline; exit 0; }
  sync_wh; ST=$(nicep scoreboard.py 2>&1 | tail -1 | cut -c1-200); logline;;
*) echo "unknown job $JOB"; exit 2;;
esac
