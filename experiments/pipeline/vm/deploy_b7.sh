#!/bin/bash
# Bundle 7 (scoring only, standing rule 2): `score` adds late_featured, late_in_top_k and dropped_from_featured to each
# daily_scores row (launches on the final featured board missing from the 00:05 PT line-up, and the reverse). The
# headline forecast is unchanged (no model.py). Copies files only; starts and stops nothing. Run outside 00:05-01:00 PT.
# usage: bash deploy_b7.sh <dir with experiments/...>    Rollback: tar xf $W/backup_b7/before.tar -C $W/experiments
set -euo pipefail
SRC=${1:?dir}; W=/home/agent/w; X=$W/experiments
export PATH=/opt/exp/bin:$PATH
test "$(md5sum < $X/pipeline/daily.py | cut -c1-8)" = e25d6237 || { echo "deployed daily.py is not b6"; exit 1; }
mkdir -p $W/backup_b7
(cd $X && tar cf $W/backup_b7/before.tar pipeline/daily.py)
echo "backed up pipeline/daily.py to $W/backup_b7/"
cp $SRC/experiments/pipeline/daily.py $X/pipeline/daily.py.new && mv $X/pipeline/daily.py.new $X/pipeline/daily.py
cd $X && python3 -c "
import inspect, pipeline.daily as D
names = [s.__name__ for s in D.STEPS]
assert names[-4:] == ['score', 'poolscore', 'earlyshock', 'raw'], names
assert D.SHADOW_DEFAULT == 'daycal,honest_a2'
print('imports ok')"
grep -q "late_in_top_k" $X/pipeline/daily.py && echo "deploy ok: b7"
