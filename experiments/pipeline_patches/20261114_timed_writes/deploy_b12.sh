#!/bin/bash
# Bundle 12 (needs Shreyas's direct approval): timed writes as cron jobs on usersim-pipeline. Touches NOTHING of the deployed pipeline:
# own tree /home/agent/w/tw (code from a pinned tarball), own results dir, own warehouse cache, own crontab block between markers.
# Refuses to run 00:05-01:00 PT. Backs up the crontab and any earlier tw tree first; checks md5s; smoke-tests imports.
# usage on usersim-pipeline:  bash deploy_b12.sh <commit> <tarball md5>
# Rollback:                   bash deploy_b12.sh rollback   (restores the crontab backup; the tw tree is moved to backup_b12/)
set -euo pipefail
W=/home/agent/w; TW=$W/tw; B=gs://usersim-bakeoff-347838016394/usersim_sim; BK=$W/backup_b12; mkdir -p $BK
export PATH=/opt/exp/bin:$PATH
H=$(TZ=America/Los_Angeles date +%H%M); [ "$H" -lt 0005 ] || [ "$H" -ge 0100 ] || { echo "inside 00:05-01:00 PT: not deploying"; exit 1; }
# review B2/B3: own exactly-matched block only (bundle 12a's block survives either order); timestamped backups; never restore a whole file
STAMP=$(date -u +%Y%m%dT%H%M%S); crontab -l > $BK/crontab.$STAMP 2>/dev/null || true
strip() { sed '/^# BEGIN usersim-b12$/,/^# END usersim-b12$/d'; }
if [ "${1:-}" = rollback ]; then
  crontab -l 2>/dev/null | strip > $BK/crontab.after_rollback.$STAMP
  grep -q "run_daily.sh" $BK/crontab.after_rollback.$STAMP || { echo "rollback result lacks the @reboot run_daily line: refusing"; exit 1; }
  crontab $BK/crontab.after_rollback.$STAMP && echo "b12 block removed (backup $BK/crontab.$STAMP)"
  [ -d $TW ] && mv $TW $BK/tw.removed_$STAMP && echo "tw tree moved to $BK"; exit 0
fi
[ -s $BK/crontab.$STAMP ] || { echo "current crontab empty or unreadable: refusing"; exit 1; }
C=${1:?commit}; WANT=${2:?tarball md5}; T=$BK/tw_code_$C.tgz
gsutil -q cp $B/deploy/b12/tw_code_$C.tgz $T
[ "$(md5sum < $T | cut -c1-8)" = "$WANT" ] || { echo "tarball md5 mismatch"; exit 1; }
[ -d $TW ] && tar cf $BK/tw_before_$(date -u +%Y%m%dT%H%M).tar -C $W tw
rm -rf $W/tw.new; mkdir -p $W/tw.new; tar xzf $T -C $W/tw.new --strip-components=1
ln -sfn $W/experiments/ph_predict/data $W/tw.new/experiments/ph_predict/data          # read-only use of the pipeline's data dir
for d in logs locks tmp cache cmt e5/why; do mkdir -p $W/tw.new/$d; done
[ -f $TW/experiments/ph_predict/results/team_pulled_0100.jsonl ] && cp $TW/experiments/ph_predict/results/team_pulled_0100.jsonl $W/tw.new/experiments/ph_predict/results/
# smoke test: imports from the new tree (no network, no writes)
(cd $W/tw.new/experiments/ph_predict && python3 -c "
import comment_forecast, early_forecast, velocity_shadow, conf_live, conf_top3_shadow, why_drivers, weekly_live, monthly_live, makerfix_shadow
print('imports ok')")
bash -n $W/tw.new/tw.sh
[ -d $TW ] && mv $TW $BK/tw.prev_$(date -u +%Y%m%dT%H%M); mv $W/tw.new $TW
# crontab: drop any earlier b12 block, append the new one
( crontab -l 2>/dev/null | strip; sed -n '/^# BEGIN usersim-b12$/,/^# END usersim-b12$/p' $TW/tw.cron ) > $BK/crontab.new.$STAMP
grep -q "run_daily.sh" $BK/crontab.new.$STAMP || { echo "new crontab lacks the @reboot run_daily line: not installing"; exit 1; }
crontab $BK/crontab.new.$STAMP
rm -f $TW/last_tick; for i in $(seq 1 26); do [ -s $TW/last_tick ] && break; sleep 5; done
[ -s $TW/last_tick ] || { echo "no tick within 130 s: rolling back"; bash $0 rollback; exit 1; }
echo "deploy ok: b12 commit $C tarball $WANT; crontab $(crontab -l | md5sum | cut -c1-8); tick: $(cat $TW/last_tick)"
