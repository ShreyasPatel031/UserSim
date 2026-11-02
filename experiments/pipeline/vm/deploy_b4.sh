#!/bin/bash
# Bundle 4: the early-vote shock backtest (ph_predict/early_shock.py, from the PR #143 session) as step `earlyshock` between
# score and raw; s_raw also uploads forecast_<d>.parquet and sim_live/pnx_<d>.json; pipeline/snapshots.py (vote snapshot
# loader it needs, not deployed before). No fetches or paid calls: it reads the warehouse and local files, idle until 14
# clean days exist (from Nov 3). Copies files only; starts and stops nothing. Run outside 00:05-01:00 PT.
# Staged: gs://usersim-bakeoff-347838016394/usersim_sim/deploy/<tag>/code.tar
# usage: bash deploy_b4.sh <tag>      then check the last line says "deploy ok"
# Rollback: tar xf $W/backup_<tag>/before.tar -C $W/experiments; cp $W/backup_<tag>/run_daily.sh $W/run_daily.sh.new && mv $W/run_daily.sh.new $W/run_daily.sh
#           rm -f $X/ph_predict/early_shock.py $X/pipeline/snapshots.py
set -euo pipefail
TAG=${1:?tag}
SRC=gs://usersim-bakeoff-347838016394/usersim_sim/deploy/$TAG
W=/home/agent/w; X=$W/experiments
export PATH=/opt/exp/bin:$PATH
mkdir -p /tmp/deploy_$TAG $W/backup_$TAG && cd /tmp/deploy_$TAG
gsutil -q cp $SRC/code.tar . && tar tf code.tar | sed 's#^experiments/##' > files.txt
(cd $X && while read -r f; do if [ -f "$f" ]; then echo "$f"; fi; done < /tmp/deploy_$TAG/files.txt > /tmp/deploy_$TAG/existing.txt
 tar cf $W/backup_$TAG/before.tar -T /tmp/deploy_$TAG/existing.txt)
cp $W/run_daily.sh $W/backup_$TAG/run_daily.sh
echo "backed up $(wc -l < /tmp/deploy_$TAG/existing.txt) files and run_daily.sh to $W/backup_$TAG/"
tar xf code.tar -C $W
cp $X/pipeline/vm/run_daily.sh $W/run_daily.sh.new && chmod +x $W/run_daily.sh.new && mv $W/run_daily.sh.new $W/run_daily.sh
cd $X && python3 -c "
import pipeline.daily as D, pipeline.snapshots
assert [s.__name__ for s in D.STEPS][-3:] == ['score', 'earlyshock', 'raw'], 'step order'
print('imports ok')"
(cd $X/ph_predict && python3 early_shock.py | tail -1)
grep -q "score,earlyshock,raw" $W/run_daily.sh && echo "deploy ok: $TAG"
