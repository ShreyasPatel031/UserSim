#!/bin/bash
# Bundle 5 (scoring only, standing rule 2): the `poolscore` step (pool Spearman and pool share of votes at d-7 complete
# and d-1 provisional -> pool_scores), between score and earlyshock. The headline forecast is unchanged (no model.py).
# Copies files only; starts and stops nothing. Run outside 00:05-01:00 PT.
# usage: bash deploy_b5.sh <dir with experiments/...>    Rollback: tar xf $W/backup_b5/before.tar -C $W/experiments;
#        cp $W/backup_b5/run_daily.sh $W/run_daily.sh.new && mv $W/run_daily.sh.new $W/run_daily.sh
set -euo pipefail
SRC=${1:?dir}; W=/home/agent/w; X=$W/experiments
export PATH=/opt/exp/bin:$PATH
mkdir -p $W/backup_b5
(cd $X && tar cf $W/backup_b5/before.tar pipeline/daily.py pipeline/vm/run_daily.sh)
cp $W/run_daily.sh $W/backup_b5/run_daily.sh
echo "backed up 2 files and run_daily.sh to $W/backup_b5/"
cp $SRC/experiments/pipeline/daily.py $X/pipeline/daily.py.new && mv $X/pipeline/daily.py.new $X/pipeline/daily.py
cp $SRC/experiments/pipeline/vm/run_daily.sh $X/pipeline/vm/run_daily.sh
cp $X/pipeline/vm/run_daily.sh $W/run_daily.sh.new && chmod +x $W/run_daily.sh.new && mv $W/run_daily.sh.new $W/run_daily.sh
cd $X && python3 -c "
import pipeline.daily as D
assert [s.__name__ for s in D.STEPS][-4:] == ['score', 'poolscore', 'earlyshock', 'raw'], 'step order'
print('imports ok')"
grep -q "score,poolscore,earlyshock,raw" $W/run_daily.sh && echo "deploy ok: b5"
