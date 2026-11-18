#!/bin/bash
# Bundle 9 (CHANGES THE HEADLINE FORECAST: needs Shreyas's approval): the honest filter drops llm_full (its prompt
# carries follower counts, which the honest filter already excludes). model.py only, one line: honest_drop() adds
# c == "llm_full". Verified on the VM with the real feature columns + LLM scores: live inputs 46 -> 45, only llm_full
# removed. Takes effect at the next forecast step. Copies files only; starts and stops nothing. Run outside 00:05-01:00 PT.
# usage: bash deploy_b9.sh <dir with experiments/...>    Rollback: tar xf $W/backup_b9/before.tar -C $W/experiments
set -euo pipefail
SRC=${1:?dir}; W=/home/agent/w; X=$W/experiments
export PATH=/opt/exp/bin:$PATH
H=$(TZ=America/Los_Angeles date +%H%M); [ "$H" -lt 0005 ] || [ "$H" -ge 0100 ] || { echo "inside 00:05-01:00 PT: not deploying"; exit 1; }
test "$(md5sum < $X/ph_predict/model.py | cut -c1-8)" = 3f816494 || { echo "deployed model.py is not the expected pre-b9 version"; exit 1; }
test "$(md5sum < $SRC/experiments/ph_predict/model.py | cut -c1-8)" = 379ff10a || { echo "source model.py is not the b9 version"; exit 1; }
mkdir -p $W/backup_b9
(cd $X && tar cf $W/backup_b9/before.tar ph_predict/model.py)
echo "backed up ph_predict/model.py to $W/backup_b9/"
cp $SRC/experiments/ph_predict/model.py $X/ph_predict/model.py.new && mv $X/ph_predict/model.py.new $X/ph_predict/model.py
cd $X && python3 -c "
import sys; sys.path.insert(0, 'ph_predict')
import model as M, pipeline.daily as D
assert M.HONEST and M.honest_drop('llm_full') and not M.honest_drop('llm_pitch') and not M.honest_drop('llm_site')
assert [s.__name__ for s in D.STEPS][:5] == ['launches', 'at_launch', 'list_check', 'snap', 'forecast']
print('imports ok')"
md5sum $X/ph_predict/model.py | cut -c1-8 | grep -q 379ff10a && echo "deploy ok: b9"
