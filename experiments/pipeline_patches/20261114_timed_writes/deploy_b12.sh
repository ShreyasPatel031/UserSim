#!/bin/bash
# Bundle 12 (needs Shreyas's direct approval): timed writes as cron jobs on usersim-pipeline. Touches NOTHING of the deployed pipeline:
# own tree /home/agent/w/tw (code from a pinned tarball), own results dir, own warehouse cache, own crontab block between markers.
# Refuses to deploy 00:05-01:00 PT (rollback always runs). Backs up the crontab and any earlier tw tree first; checks md5s; smoke-tests imports.
# usage on usersim-pipeline:  bash deploy_b12.sh <commit> <tarball md5>
# Rollback:                   bash deploy_b12.sh rollback   (restores the crontab backup; the tw tree is moved to backup_b12/)
set -euo pipefail
W=/home/agent/w; TW=$W/tw; B=gs://usersim-bakeoff-347838016394/usersim_sim; BK=$W/backup_b12; mkdir -p $BK
export PATH=/opt/exp/bin:$PATH
# review B2/B3: own exactly-matched block only (bundle 12a's block survives either order); timestamped backups; never restore a whole file
STAMP=$(date -u +%Y%m%dT%H%M%S); crontab -l > $BK/crontab.$STAMP 2>/dev/null || true
strip() { sed '/^# BEGIN usersim-b12$/,/^# END usersim-b12$/d'; }
if [ "${1:-}" = rollback ]; then
  crontab -l 2>/dev/null | strip > $BK/crontab.after_rollback.$STAMP
  grep -q "run_daily.sh" $BK/crontab.after_rollback.$STAMP || { echo "rollback result lacks the @reboot run_daily line: refusing"; exit 1; }
  crontab $BK/crontab.after_rollback.$STAMP && echo "b12 block removed (backup $BK/crontab.$STAMP)"
  [ -d $TW ] && mv $TW $BK/tw.removed_$STAMP && echo "tw tree moved to $BK"; exit 0
fi
# time guard below the rollback branch: rollback is always allowed (orchestrator 12:36Z Nov 14)
H=$(TZ=America/Los_Angeles date +%H%M); [ "$H" -lt 0005 ] || [ "$H" -ge 0100 ] || { echo "inside 00:05-01:00 PT: not deploying"; exit 1; }
[ "$(id -un)" = agent ] || { echo "run as user agent (the crontab owner): not deploying"; exit 1; }
[ -s $BK/crontab.$STAMP ] || { echo "current crontab empty or unreadable: refusing"; exit 1; }
C=${1:?commit}; WANT=${2:?tarball md5}; T=$BK/tw_code_$C.tgz
gsutil -q cp $B/deploy/b12/tw_code_$C.tgz $T
[ "$(md5sum < $T | cut -c1-8)" = "$WANT" ] || { echo "tarball md5 mismatch"; exit 1; }
[ -d $TW ] && tar cf $BK/tw_before_$(date -u +%Y%m%dT%H%M).tar -C $W tw
rm -rf $W/tw.new; mkdir -p $W/tw.new; tar xzf $T -C $W/tw.new --strip-components=1
ln -sfn $W/experiments/ph_predict/data $W/tw.new/experiments/ph_predict/data          # read-only use of the pipeline's data dir
for d in logs locks tmp cache cmt e5/why; do mkdir -p $W/tw.new/$d; done
# E5 vm_writers (pinned tarball md5 cd7fcebd, E5 12:49Z Nov 14: track_record >= 10 ranked day rule + 00:05 prob calibration refit on 183 days, 05bb6003; E5 holds further changes) + the salt for held_team_* (mode 600; read only to hash, never printed)
E5W_MD5=cd7fcebd; gsutil -q cp $B/tmp/e5/vm_writers/e5_vm_writers.tgz $BK/e5_vm_writers.tgz
[ "$(md5sum < $BK/e5_vm_writers.tgz | cut -c1-8)" = "$E5W_MD5" ] || { echo "e5 vm_writers tarball md5 mismatch: not deploying"; exit 1; }
mkdir -p $W/tw.new/e5_vm_writers $W/tw.new/e5_assets/early; tar xzf $BK/e5_vm_writers.tgz -C $W/tw.new/e5_vm_writers
(umask 077; gsutil -q cp $B/raw/population/_salt $W/tw.new/e5_assets/early/salt) || { echo "salt copy failed: not deploying"; exit 1; }
bash -n $W/tw.new/e5_vm_writers/vm_writers/run.sh; command -v python > /dev/null || { echo "vm_writers run.sh calls python: not on PATH"; exit 1; }
[ -f $TW/experiments/ph_predict/results/team_pulled_0100.jsonl ] && cp $TW/experiments/ph_predict/results/team_pulled_0100.jsonl $W/tw.new/experiments/ph_predict/results/
# HARD IMPORT GATE (orchestrator 09:12Z Nov 14): every module each job imports, exactly as tw.sh runs it from cron (user agent,
# PYTHONPATH unset unless tw.sh sets it, /opt/exp/bin/python3, tw.sh's cwd per job; paths of the new tree = the final tree's layout).
# Any ImportError aborts the deploy before the live tree or the crontab change. No network, no writes, scripts are not executed.
N=$W/tw.new; PYG="env -u PYTHONPATH /opt/exp/bin/python3 $N/import_gate.py"; P=$N/experiments/ph_predict
gate() { echo "gate: $1"; (eval "$2") || { echo "import gate failed: $1: not deploying"; exit 1; }; }
gate "tw.sh python jobs" "cd $P && $PYG comment_forecast.py early_forecast.py velocity_shadow.py conf_live.py conf_top3_shadow.py why_drivers.py \
  weekly_live.py monthly_live.py makerfix_shadow.py makerfix_score.py growth.py web_forecast_0005.py scoreboard.py arm2_shap.py"
gate "h25_shadow (tw.sh PYTHONPATH)" "cd $W/experiments/ph_predict && env PYTHONPATH=/home/agent/w/mk:.:$N/h25 /opt/exp/bin/python3 $N/import_gate.py $N/h25/h25_shadow.py"
gate "readable_shadow (tw.sh PYTHONPATH)" "cd $W/experiments/ph_predict && env PYTHONPATH=/home/agent/w/mk:. /opt/exp/bin/python3 $N/import_gate.py $N/h25/readable_shadow.py"
gate "vs_reconcile (-m)" "cd $N/experiments && $PYG -m:pipeline.vs_reconcile"
gate "E5 follow_shadow (python3 -I)" "cd $P && env -u PYTHONPATH /opt/exp/bin/python3 -I $N/import_gate.py --isolated $N/e5/e5f/follow_shadow.py"
gate "E5 team_shadow" "cd $N/e5/e5wt/experiments/simlab && $PYG team_shadow.py"
gate "E5 why_writer" "cd $N/e5/e5why && $PYG experiments/simlab/why_writer.py"
gate "E5 vm_writers (run.sh: cd simlab, PYTHONPATH=vm_writers)" "cd $N/e5_vm_writers/vm_writers/simlab && env PYTHONPATH=$N/e5_vm_writers/vm_writers \
  /opt/exp/bin/python3 $N/import_gate.py prob_writer.py period_parts.py period_score.py period_writer.py track_record.py held_team_shadow.py"
# the published 00:05 arm-2 branch: the pipeline's forecast.py as the daily step runs it (cwd ph_predict, PYTHONPATH unset): this imports
# h25_live from ~/w/arm2_live and, through it, training_window -> ctrl / honest (the Nov 14 miss)
gate "arm-2 branch (pipeline forecast.py)" "cd $W/experiments/ph_predict && $PYG forecast.py"
bash -n $W/tw.new/tw.sh
[ -d $TW ] && mv $TW $BK/tw.prev_$(date -u +%Y%m%dT%H%M); mv $W/tw.new $TW
# crontab: drop any earlier b12 block, append the new one
( crontab -l 2>/dev/null | strip; sed -n '/^# BEGIN usersim-b12$/,/^# END usersim-b12$/p' $TW/tw.cron ) > $BK/crontab.new.$STAMP
grep -q "run_daily.sh" $BK/crontab.new.$STAMP || { echo "new crontab lacks the @reboot run_daily line: not installing"; exit 1; }
crontab $BK/crontab.new.$STAMP
rm -f $TW/last_tick; for i in $(seq 1 26); do [ -s $TW/last_tick ] && break; sleep 5; done
[ -s $TW/last_tick ] || { echo "no tick within 130 s: rolling back"; bash $0 rollback; exit 1; }
echo "deploy ok: b12 commit $C tarball $WANT; crontab $(crontab -l | md5sum | cut -c1-8); tick: $(cat $TW/last_tick)"
