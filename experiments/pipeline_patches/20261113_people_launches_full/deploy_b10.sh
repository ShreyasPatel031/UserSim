#!/bin/bash
# Bundle 10 (pipeline change: needs Shreyas's direct approval): full people + launches tables. Copies files only; starts and
# stops nothing; the one-off rebuilds are separate commands (README). Run outside 00:05-01:00 PT.
# usage: bash deploy_b10.sh <dir with experiments/...>    Rollback: tar xf $W/backup_b10/before.tar -C $W/experiments
set -euo pipefail
SRC=${1:?dir}; W=/home/agent/w; X=$W/experiments; Pd=$SRC/experiments/pipeline_patches/20261113_people_launches_full
export PATH=/opt/exp/bin:$PATH
H=$(TZ=America/Los_Angeles date +%H%M); [ "$H" -lt 0005 ] || [ "$H" -ge 0100 ] || { echo "inside 00:05-01:00 PT: not deploying"; exit 1; }
m() { md5sum < "$1" | cut -c1-8; }
test "$(m $X/pipeline/daily.py)" = 27f0578d || { echo "deployed daily.py is not the expected pre-b10 version ($(m $X/pipeline/daily.py))"; exit 1; }
test "$(m $X/pipeline/warehouse.py)" = c89671dc || { echo "deployed warehouse.py is not the expected pre-b10 version"; exit 1; }
test "$(m $Pd/daily.py)" = 6e80e47e && test "$(m $Pd/warehouse.py)" = d5a50870 || { echo "source files are not the b10 versions"; exit 1; }
mkdir -p $W/backup_b10
(cd $X && tar cf $W/backup_b10/before.tar pipeline/daily.py pipeline/warehouse.py)
echo "backed up pipeline/daily.py pipeline/warehouse.py to $W/backup_b10/"
for f in daily warehouse people_full launches_backfill; do cp $Pd/$f.py $X/pipeline/$f.py.new && mv $X/pipeline/$f.py.new $X/pipeline/$f.py; done
cd $X && python3 -c "
import pipeline.daily as D, pipeline.warehouse as W, pipeline.people_full as PF, pipeline.launches_backfill as LB
names = [s.__name__ for s in D.STEPS]
assert names[:5] == ['launches', 'at_launch', 'list_check', 'snap', 'forecast'] and names.index('people_full') == names.index('people') + 1
assert W.KEYS['people_records'] == ['person'] and 'launch_extra' in dir(D)
print('imports ok')"
test "$(m $X/pipeline/daily.py)" = 6e80e47e && echo "deploy ok: b10"
