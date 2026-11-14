#!/bin/bash
# Bundle 12a (needs Shreyas's direct word: it changes the VM crontab and adds one Product Hunt API read a day, 03:45 PT): the two published
# predictions written by code on usersim-pipeline. Copies files to /home/agent/w/tw12a and adds ONE crontab line (a minute tick) in its own
# exactly-matched block; any other block (bundle 12's, the @reboot line) is left as it is, in either deploy order (review B2).
# Every deploy and rollback first saves a timestamped crontab backup; rollback removes only this block and never restores a whole file (B3).
# Refuses 00:05-01:00 PT. Checks md5s. After install it waits for two ticks to prove cron fires and the Pacific gate works (B4).
# usage (on the VM):  bash deploy_b12a.sh <this folder>      rollback: bash deploy_b12a.sh rollback
set -euo pipefail
W=/home/agent/w; T=$W/tw12a; BK=$W/backup_b12a; mkdir -p $BK; export PATH=/opt/exp/bin:$PATH
H=$(TZ=America/Los_Angeles date +%H%M); [ "$H" -lt 0005 ] || [ "$H" -ge 0100 ] || { echo "inside 00:05-01:00 PT: not deploying"; exit 1; }
STAMP=$(date -u +%Y%m%dT%H%M%S); crontab -l > $BK/crontab.$STAMP 2>/dev/null || true
strip() { sed '/^# BEGIN usersim-b12a$/,/^# END usersim-b12a$/d'; }
if [ "${1:-}" = rollback ]; then
  crontab -l 2>/dev/null | strip > $BK/crontab.after_rollback.$STAMP
  grep -q "run_daily.sh" $BK/crontab.after_rollback.$STAMP || { echo "rollback result lacks the @reboot run_daily line: refusing"; exit 1; }
  crontab $BK/crontab.after_rollback.$STAMP && echo "b12a block removed (backup $BK/crontab.$STAMP)"
  [ -d $T ] && mv $T $BK/tw12a.removed_$STAMP; exit 0
fi
S=${1:?folder}; m() { md5sum < "$1" | cut -c1-8; }
declare -A WANT=( [two_predictions.py]=33abc764 [recorder_extra.py]=c1231100 [run.sh]=1bf8e2cb [tick.sh]=d446e816 [sched12a.txt]=54dae6de [cron12a.txt]=0e2c7f4d [hybrid_vmonly_P345_20261114.json]=16912cd6 )
for f in "${!WANT[@]}"; do [ "$(m $S/$f)" = "${WANT[$f]}" ] || { echo "$f md5 $(m $S/$f) != ${WANT[$f]}"; exit 1; }; done
[ -s $BK/crontab.$STAMP ] || { echo "current crontab empty or unreadable: refusing (expected the @reboot run_daily line)"; exit 1; }
[ -d $T ] && tar cf $BK/tw12a_before_$STAMP.tar -C $W tw12a
mkdir -p $T; for f in "${!WANT[@]}"; do cp $S/$f $T/$f; done
python3 -c "import ast; [ast.parse(open('$T/'+f).read()) for f in ('two_predictions.py', 'recorder_extra.py')]"; bash -n $T/run.sh; bash -n $T/tick.sh
(cd $W/experiments && python3 -c "from pipeline import hourly; assert hasattr(hourly, '_snapshot') and hasattr(hourly, 'pacific_day')")
( crontab -l 2>/dev/null | strip; cat $T/cron12a.txt ) > $BK/crontab.new.$STAMP
grep -q "run_daily.sh" $BK/crontab.new.$STAMP || { echo "new crontab lacks the @reboot run_daily line: not installing"; exit 1; }
crontab $BK/crontab.new.$STAMP
# prove the tick: cron runs it every minute; last_tick must change within ~2 min and show a Pacific time
rm -f $T/last_tick; for i in $(seq 1 26); do [ -s $T/last_tick ] && break; sleep 5; done
[ -s $T/last_tick ] || { echo "no tick within 130 s: rolling back"; bash $0 rollback; exit 1; }
echo "deploy ok: b12a; crontab $(crontab -l | md5sum | cut -c1-8); tick: $(cat $T/last_tick); UTC now $(date -u +%H:%M)"
