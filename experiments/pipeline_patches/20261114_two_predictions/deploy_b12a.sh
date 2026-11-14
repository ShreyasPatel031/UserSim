#!/bin/bash
# Bundle 12a (needs Shreyas's direct word: it changes the VM crontab and adds two Product Hunt API reads a day): the two published
# predictions written by code on usersim-pipeline. Copies 5 files to /home/agent/w/tw12a and adds one crontab block; the deployed pipeline
# code is not touched. Refuses 00:05-01:00 PT; checks md5s; backs up the crontab; rollback restores it.
# usage (on the VM, from a checkout or a copy of this folder):  bash deploy_b12a.sh <this folder>     rollback: bash deploy_b12a.sh rollback
set -euo pipefail
W=/home/agent/w; T=$W/tw12a; BK=$W/backup_b12a; mkdir -p $BK; export PATH=/opt/exp/bin:$PATH
H=$(TZ=America/Los_Angeles date +%H%M); [ "$H" -lt 0005 ] || [ "$H" -ge 0100 ] || { echo "inside 00:05-01:00 PT: not deploying"; exit 1; }
if [ "${1:-}" = rollback ]; then crontab $BK/crontab.before && echo "crontab restored"; [ -d $T ] && mv $T $BK/tw12a.removed_$(date -u +%Y%m%dT%H%M); exit 0; fi
S=${1:?folder}; m() { md5sum < "$1" | cut -c1-8; }
declare -A WANT=( [two_predictions.py]=fa2cce90 [recorder_extra.py]=c1231100 [run.sh]=0bb58bfc [cron12a.txt]=9fda1e7d [hybrid_vmonly_P345_20261114.json]=16912cd6 )
for f in "${!WANT[@]}"; do [ "$(m $S/$f)" = "${WANT[$f]}" ] || { echo "$f md5 $(m $S/$f) != ${WANT[$f]}"; exit 1; }; done
crontab -l > $BK/crontab.before 2>/dev/null || true
[ -d $T ] && tar cf $BK/tw12a_before_$(date -u +%Y%m%dT%H%M).tar -C $W tw12a
mkdir -p $T; for f in "${!WANT[@]}"; do cp $S/$f $T/$f; done
python3 -c "import ast; [ast.parse(open('$T/'+f).read()) for f in ('two_predictions.py', 'recorder_extra.py')]"; bash -n $T/run.sh
(cd /home/agent/w/experiments && python3 -c "from pipeline import hourly; assert hasattr(hourly, '_snapshot') and hasattr(hourly, 'pacific_day')") 
( crontab -l 2>/dev/null | sed '/# BEGIN usersim-b12a/,/# END usersim-b12a/d'; cat $T/cron12a.txt ) | crontab -
crontab -l | grep -q "@reboot sleep 60 && /home/agent/w/run_daily.sh" || { crontab $BK/crontab.before; echo "boot line missing: rolled back"; exit 1; }
echo "deploy ok: b12a, crontab $(crontab -l | md5sum | cut -c1-8), $(crontab -l | grep -c tw12a/run.sh) job lines"
