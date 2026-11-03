#!/bin/bash
# Bundle 8 (recording only, standing rule 2): `launches` uploads data/today/<day>.json to raw/daily/<day>/today_0005.json
# right after the line-up read (~00:06 PT), the trigger for Data Feeder's at-launch capture. The
# headline forecast is unchanged (no model.py). Copies files only; starts and stops nothing. Run outside 00:05-01:00 PT.
# usage: bash deploy_b8.sh <dir with experiments/...>    Rollback: tar xf $W/backup_b8/before.tar -C $W/experiments
set -euo pipefail
SRC=${1:?dir}; W=/home/agent/w; X=$W/experiments
export PATH=/opt/exp/bin:$PATH
test "$(md5sum < $X/pipeline/daily.py | cut -c1-8)" = d6f4190c || { echo "deployed daily.py is not b7"; exit 1; }
mkdir -p $W/backup_b8
(cd $X && tar cf $W/backup_b8/before.tar pipeline/daily.py)
echo "backed up pipeline/daily.py to $W/backup_b8/"
cp $SRC/experiments/pipeline/daily.py $X/pipeline/daily.py.new && mv $X/pipeline/daily.py.new $X/pipeline/daily.py
cd $X && python3 -c "
import inspect, pipeline.daily as D
names = [s.__name__ for s in D.STEPS]
assert names[:2] == ['launches', 'at_launch'] and names[-4:] == ['score', 'poolscore', 'earlyshock', 'raw'], names
assert D.SHADOW_DEFAULT == 'daycal,honest_a2'
print('imports ok')"
grep -q "today_0005.json" $X/pipeline/daily.py && echo "deploy ok: b8"
