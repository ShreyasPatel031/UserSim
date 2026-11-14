#!/bin/bash
# Deploy the today-rows fix = features.py 033d7bd7 ALONE (orchestrator review 16:44Z Nov 14: forecast.py / h25_live.py hunks are a later patch).
# Run ON usersim-pipeline as agent, after staging this folder to ~/w/today_rows.new (scp features.py test_today_rows.py dryrun_tonight.py
# import_gate.py deploy_today_rows.sh). Needs Shreyas's direct word.
#   bash deploy_today_rows.sh deploy     check 981c5ded -> gates + test on the STAGED copy -> backup -> atomic install -> test + dry run on the live path
#   bash deploy_today_rows.sh check      the same pre-install checks + dry run on the STAGED copy; changes nothing (any time)
#   bash deploy_today_rows.sh rollback   restore the 981c5ded backup (always allowed, any time)
# Refuses to deploy 00:05-01:00 PT. Any failure after install rolls back automatically.
set -uo pipefail
W=/home/agent/w; P=$W/experiments/ph_predict; N=$W/today_rows.new; BK=$W/backup_today_rows; PY=/opt/exp/bin/python3
OLD=981c5ded; NEW=033d7bd7; T=$W/phops_tm/today_rows_deploy; mkdir -p $T
m8() { md5sum "$1" | cut -c1-8; }
rollback() { [ -f $BK/features.py ] && [ "$(m8 $BK/features.py)" = $OLD ] || { echo "ROLLBACK: no $OLD backup at $BK"; exit 2; }
  cp $BK/features.py $P/features.py.rb && mv $P/features.py.rb $P/features.py && echo "ROLLED BACK: $P/features.py = $(m8 $P/features.py)"; }
MODE=${1:-}
case "$MODE" in
rollback) rollback; exit $?;;
deploy|check) ;;
*) echo "usage: $0 deploy|check|rollback"; exit 64;;
esac
[ "$MODE" = check ] || H=$(TZ=America/Los_Angeles date +%H%M); [ "$MODE" = check ] || [ "$H" -lt 0005 ] || [ "$H" -ge 0100 ] || { echo "inside 00:05-01:00 PT: not deploying"; exit 1; }
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
if [ "$MODE" = check ]; then   # read-only rehearsal: dry run on the staged copy, nothing installed
  env PYTHONPATH=$N:. nice $PY $T/bin/dryrun_tonight.py $T; rc=$?; echo "CHECK DONE rc=$rc (nothing changed)"; exit $rc; fi
# (2) backup, (3) atomic install
mkdir -p $BK && cp -p $P/features.py $BK/features.py && [ "$(m8 $BK/features.py)" = $OLD ] || { echo "backup failed: stop"; exit 1; }
cp $N/features.py $P/features.py.new && mv $P/features.py.new $P/features.py
[ "$(m8 $P/features.py)" = $NEW ] || { echo "install md5 mismatch: rolling back"; rollback; exit 1; }
echo "installed $NEW (backup $BK/features.py $OLD)"
# (4b) gates + test on the LIVE path, (5) scratch dry run of tonight's path; any failure -> rollback
ok=1
env -u PYTHONPATH $PY $T/bin/import_gate.py $P/forecast.py || ok=0
env PYTHONPATH=$W/arm2_live:. $PY $T/bin/import_gate.py $W/arm2_live/h25_live.py || ok=0
env PYTHONPATH=. $PY $T/bin/test_today_rows.py $(realpath $P/data) $D 2099-01-01 || ok=0
env PYTHONPATH=. nice $PY $T/bin/dryrun_tonight.py $T || ok=0
[ $ok = 1 ] || { echo "POST-INSTALL CHECK FAILED: rolling back"; rollback; exit 1; }
echo "DEPLOYED today-rows fix: $P/features.py = $NEW; rollback: bash $N/deploy_today_rows.sh rollback"
