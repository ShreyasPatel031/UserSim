#!/bin/bash
# PH ops timed shadow writes, run by cron on usersim-pipeline (DRAFT, NOT INSTALLED; needs Shreyas's approval).
# Replaces the session-driven 2-hourly check for the steps that must run on time. Every step is idempotent: it runs only
# when its output is missing in the bucket. Shadow files only; never touches the deployed 00:05 forecast.
# Install (after approval):  crontab -l | cat - docs/patches/ph_ops_crontab.txt | crontab -
set -u
cd ~/w/experiments/ph_predict || exit 1
export TMPDIR=~/tmp_phops; mkdir -p "$TMPDIR"
PY=/opt/exp/bin/python3; B=gs://usersim-bakeoff-347838016394/usersim_sim
T=$(TZ=America/Los_Angeles date +%F); Y=$(TZ=America/Los_Angeles date -d yesterday +%F)
H=$(TZ=America/Los_Angeles date +%-H); M=$(TZ=America/Los_Angeles date +%-M); NOWM=$((H*60+M))
MON=$($PY -c "import pandas as pd;t=pd.Timestamp('$T');print((t-pd.Timedelta(days=t.dayofweek)).strftime('%Y-%m-%d'))")
YMON=$($PY -c "import pandas as pd;t=pd.Timestamp('$Y');print((t-pd.Timedelta(days=t.dayofweek)).strftime('%Y-%m-%d'))")
LOG=~/ph_ops_cron.log
miss() { ! gsutil -q stat "$1" 2>/dev/null; }
run() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; timeout 1800 "$@" >> "$LOG" 2>&1; }
[ $NOWM -ge 5 ] && [ $NOWM -lt 60 ] && exit 0                 # never 00:05-01:00 PT
# day-end lines for yesterday (from 00:17 PT)
miss $B/results/weekly_live/${YMON}_${Y}_dayend.json && run $PY weekly_live.py dayend $Y
miss $B/results/monthly_live/${Y:0:7}_${Y}_dayend.json && run $PY monthly_live.py dayend $Y
if [ $NOWM -ge 60 ]; then
  if miss $B/results/shadow_makerfix/$T.json; then
    run nice -n 10 env LGB_THREADS=3 $PY makerfix_shadow.py $T && gsutil -q cp results/shadow_makerfix/$T.json $B/results/shadow_makerfix/$T.json
  fi
  miss $B/results/web/confidence/$T.json && run $PY conf_live.py $T
  for P in P030:30 P0:45 P1:60 P2:120 P3:180 P4:240; do
    n=${P%%:*}; m=${P##*:}
    [ $NOWM -ge $m ] && miss $B/results/early_forecast/${T}_$n.json && run env CF_WORK=$TMPDIR/cmt $PY comment_forecast.py live $T $n
  done
  miss $B/results/weekly_live/${YMON}_${Y}_running.json && run $PY weekly_live.py running $Y
  miss $B/results/monthly_live/${Y:0:7}_${Y}_running.json && run $PY monthly_live.py running $Y
fi
# reveal-relative and fixed-time points (early_forecast.py refuses points whose time has not passed)
for P in R0 R0q R0h R1 R2 R4 C05 C06 C12 C16; do
  miss $B/results/early_forecast/${T}_$P.json && run $PY early_forecast.py live $T $P votes
done
[ $H -ge 4 ] && [ "$(date +%u)" != 1 ] && miss $B/results/weekly_live/${MON}_${T}_est.json && run $PY weekly_live.py est $T
gsutil -q stat $B/results/early_forecast/${T}_R4.json && miss $B/results/weekly_live/${MON}_${T}_R4.json && run $PY weekly_live.py r4 $T
# website files and scoreboard at the 02:17 and 08:17 runs
if [ $H -eq 2 ] || [ $H -eq 8 ]; then
  [ $H -eq 2 ] && run $PY web_forecast_0005.py
  [ $H -eq 8 ] && run $PY conf_live.py score
  run $PY scoreboard.py
fi
rm -rf "$TMPDIR"/*
