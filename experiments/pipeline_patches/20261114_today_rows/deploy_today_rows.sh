#!/bin/bash
# Deploy the today-rows fix = features.py 033d7bd7 ALONE (orchestrator review 16:44Z Nov 14: forecast.py / h25_live.py hunks are a later patch).
# Run ON usersim-pipeline as agent, after staging this folder to ~/w/today_rows.new (scp features.py test_today_rows.py dryrun_tonight.py
# import_gate.py deploy_today_rows.sh). Needs Shreyas's direct word.
#   bash deploy_today_rows.sh deploy     check 981c5ded -> gates + test on the STAGED copy -> backup -> atomic install -> test + dry run on the live path
#   bash deploy_today_rows.sh check      the same pre-install checks + dry run on the STAGED copy; changes nothing (any time)
#   bash deploy_today_rows.sh rollback   restore the 981c5ded backup (always allowed, any time)
# Refuses to deploy 23:30-01:00 PT (its post-install dry run must not overlap the 00:05 forecast). Runs as user agent only.
# Any failure after install rolls back automatically. State file ~/w/today_rows_state: "installed_unverified" is written BEFORE the install;
# a rerun of `deploy` that finds it (and the live file at NEW) resumes the live-path checks, then verifies or rolls back.
# Safe order (orchestrator 20:21Z): today-rows -> marker (this script) -> 12a.2 -> fixed-prior weights -> live-code 1 -> bundle 12.4.
set -uo pipefail
W=/home/agent/w; P=$W/experiments/ph_predict; N=$W/today_rows.new; BK=$W/backup_today_rows; PY=/opt/exp/bin/python3
OLD=981c5ded; NEW=033d7bd7; T=$W/phops_tm/today_rows_deploy; mkdir -p $T; ST=$W/today_rows_state; GSM=gs://usersim-bakeoff-347838016394/usersim_sim/results/web/today_rows_fix.json
m8() { md5sum "$1" | cut -c1-8; }
# the ONE fix-date marker: local file (tw.sh reads it -> TODAY_ROWS_FIX_DEPLOYED / TODAY_BUG_FIXED for run.sh) + bucket copy (scoreboard.py reads it)
write_marker() {   # $1 local path, $2 bucket path
  FX=$(TZ=America/Los_Angeles date +%H%M); if [ "$FX" -lt 0005 ]; then FROM=$(TZ=America/Los_Angeles date +%F); else FROM=$(TZ=America/Los_Angeles date -d tomorrow +%F); fi
  echo "{\"fixed_from\": \"$FROM\", \"features_md5\": \"$NEW\", \"installed_at\": \"$(date -u +%FT%TZ)\"}" > $1
  gsutil -q cp $1 $2 || echo "WARN: bucket copy of the marker failed (local marker written)"; }
remove_marker() { rm -f $1; gsutil -q rm $2 2>/dev/null || true; }
rollback() { [ -f $BK/features.py ] && [ "$(m8 $BK/features.py)" = $OLD ] || { echo "ROLLBACK: no $OLD backup at $BK"; exit 2; }
  cp $BK/features.py $P/features.py.rb && mv $P/features.py.rb $P/features.py && echo "ROLLED BACK: $P/features.py = $(m8 $P/features.py)"
  remove_marker $W/today_rows_fix.json $GSM; echo "rolled_back $(date -u +%FT%TZ)" > $ST; }
MODE=${1:-}
case "$MODE" in
rollback) [ "$(id -un)" = agent ] || { echo "run as user agent"; exit 1; }; rollback; exit $?;;
deploy|check) ;;
*) echo "usage: $0 deploy|check|rollback"; exit 64;;
esac
if [ "$MODE" = deploy ]; then
  [ "$(id -un)" = agent ] || { echo "run as user agent (the crontab owner): not deploying"; exit 1; }
  H=$(TZ=America/Los_Angeles date +%H%M); { [ "$H" -ge 0100 ] && [ "$H" -lt 2330 ]; } || { echo "inside 23:30-01:00 PT: not deploying"; exit 1; }
fi
post_checks() {   # live-path gates + test + dry run; marker on success; any failure -> rollback
  mkdir -p $T/bin && cp $N/test_today_rows.py $N/dryrun_tonight.py $N/import_gate.py $T/bin/; cd $P; D=$(ls $P/data/today | sort | tail -1 | cut -c1-10)
  ok=1
  env -u PYTHONPATH $PY $T/bin/import_gate.py $P/forecast.py || ok=0
  env PYTHONPATH=$W/arm2_live:. $PY $T/bin/import_gate.py $W/arm2_live/h25_live.py || ok=0
  env PYTHONPATH=. $PY $T/bin/test_today_rows.py $(realpath $P/data) $D 2099-01-01 || ok=0
  env PYTHONPATH=. nice $PY $T/bin/dryrun_tonight.py $T || ok=0
  [ $ok = 1 ] || { echo "POST-INSTALL CHECK FAILED: rolling back"; rollback; exit 1; }
  write_marker $W/today_rows_fix.json $GSM; echo "verified $(date -u +%FT%TZ)" > $ST
  echo "DEPLOYED today-rows fix: $P/features.py = $NEW; marker $(cat $W/today_rows_fix.json); rollback: bash $N/deploy_today_rows.sh rollback"; exit 0; }
if [ "$MODE" = deploy ] && [ -f $ST ] && grep -q installed_unverified $ST && [ "$(m8 $P/features.py)" = $NEW ]; then
  echo "resuming: a previous deploy installed $NEW but did not finish its checks"; post_checks; fi
# (1) versions. Other features.py copies on the VM (Nov 14 16:50Z): ~/w/fa/features.py 49388f33 (stray single file, no data dir, imported by
# nothing - no change); ~/w/phops_repro and ~/w/phops_tm are scratch. Every include_today caller (forecast.py, arm2_live/h25_live.py,
# ~/w/h25/*.py, clean_live, makerfix_shadow, ...) imports ph_predict/features.py (cwd ph_predict / PYTHONPATH .).
[ "$(m8 $P/features.py)" = $OLD ] || { echo "live features.py is $(m8 $P/features.py), expected $OLD: stop"; exit 1; }
[ "$(m8 $N/features.py)" = $NEW ] || { echo "staged features.py is $(m8 $N/features.py), expected $NEW: stop"; exit 1; }
for f in $(cd $W && find . -name features.py -not -path "./backup*" -not -path "./phops_*" -not -path "./today_rows.new/*"); do echo "copy: $f $(m8 $W/$f)"; done
# (4a) test on the STAGED copy before anything changes. Helper scripts run from $T/bin (no features.py there), so the features module is
# the one PYTHONPATH / cwd names, never a copy next to the script.
mkdir -p $T/bin && cp $N/test_today_rows.py $N/dryrun_tonight.py $N/import_gate.py $T/bin/
D=$(ls $P/data/today | sort | tail -1 | cut -c1-10); cd $P
env PYTHONPATH=$N:. $PY $T/bin/test_today_rows.py $(realpath $P/data) $D 2099-01-01 > $T/staged_test.log 2>&1; rc=$?; grep -v Warn $T/staged_test.log | tail -6
grep -q "features from $N/features.py" $T/staged_test.log || { echo "staged test did not load the staged copy: stop"; exit 1; }
[ $rc = 0 ] || { echo "TEST FAIL on staged copy: stop (nothing changed)"; exit 1; }
if [ "$MODE" = check ]; then   # read-only rehearsal: dry run on the staged copy + marker write/remove on scratch paths; nothing live changed
  env PYTHONPATH=$N:. nice $PY $T/bin/dryrun_tonight.py $T; rc=$?
  TM=$T/marker_test.json; TG=gs://usersim-bakeoff-347838016394/usersim_sim/tmp/ph_ops/marker_test/today_rows_fix.json
  write_marker $TM $TG; mk=$( [ -s $TM ] && gsutil -q stat $TG && echo written || echo FAIL ); echo "marker test write: $mk $(cat $TM 2>/dev/null)"
  remove_marker $TM $TG; rm_=$( [ ! -e $TM ] && ! gsutil -q stat $TG 2>/dev/null && echo removed || echo FAIL ); echo "marker test remove: $rm_"
  [ "$mk" = written ] && [ "$rm_" = removed ] || rc=1
  echo "CHECK DONE rc=$rc (nothing live changed)"; exit $rc; fi
# (2) backup, (3) atomic install
mkdir -p $BK && cp -p $P/features.py $BK/features.py && [ "$(m8 $BK/features.py)" = $OLD ] || { echo "backup failed: stop"; exit 1; }
echo "installed_unverified $(date -u +%FT%TZ)" > $ST
cp $N/features.py $P/features.py.new && mv $P/features.py.new $P/features.py
[ "$(m8 $P/features.py)" = $NEW ] || { echo "install md5 mismatch: rolling back"; rollback; exit 1; }
echo "installed $NEW (backup $BK/features.py $OLD)"
# (4b)-(6): live-path checks, then the marker
post_checks
