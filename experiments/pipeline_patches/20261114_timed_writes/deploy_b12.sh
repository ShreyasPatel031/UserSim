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
if [ "${1:-}" = rollback ]; then
  crontab $BK/crontab.before && echo "crontab restored ($(md5sum < $BK/crontab.before | cut -c1-8))"
  [ -d $TW ] && mv $TW $BK/tw.removed_$(date -u +%Y%m%dT%H%M) && echo "tw tree moved to $BK"; exit 0
fi
C=${1:?commit}; WANT=${2:?tarball md5}; T=$BK/tw_code_$C.tgz
gsutil -q cp $B/deploy/b12/tw_code_$C.tgz $T
[ "$(md5sum < $T | cut -c1-8)" = "$WANT" ] || { echo "tarball md5 mismatch"; exit 1; }
crontab -l > $BK/crontab.before 2>/dev/null || true
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
( crontab -l 2>/dev/null | sed '/# BEGIN usersim-b12/,/# END usersim-b12/d'; sed -n '/# BEGIN usersim-b12/,/# END usersim-b12/p' $TW/tw.cron ) | crontab -
crontab -l | grep -q "@reboot sleep 60 && /home/agent/w/run_daily.sh" || { echo "run_daily.sh @reboot line missing after install: rolling back"; crontab $BK/crontab.before; exit 1; }
echo "deploy ok: b12 commit $C tarball $WANT; crontab $(crontab -l | md5sum | cut -c1-8) ($(crontab -l | grep -c usersim/w/tw\\\|/w/tw/tw.sh) job lines)"
