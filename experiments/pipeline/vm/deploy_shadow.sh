#!/bin/bash
# Bundle: shadow forecasts (E1 v2, day-calibrated weekly), weekly scoring, the people step reading Data Feeder's daily
# delivery (raw/ph_people_daily), forecast.py saving the launch model's raw predictions. On usersim-pipeline as agent.
# Copies files only; starts and stops nothing. Run outside 00:05-01:00 PT. Needs Shreyas's approval to run.
# Staged: gs://usersim-bakeoff-347838016394/usersim_sim/deploy/<tag>/{code.tar, e1v2/*, daycal/*}
# usage: bash deploy_shadow.sh <tag>      then check the last line says "deploy ok"
# Rollback: tar xf $W/backup_<tag>/before.tar -C $W/experiments; cp $W/backup_<tag>/run_daily.sh $W/run_daily.sh.new && mv $W/run_daily.sh.new $W/run_daily.sh
#           (and remove $X/ph_predict/data/shadow to switch the shadows off)
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
# run_daily.sh may be executing (bash reads scripts as it goes): write a new file and rename it into place
cp $X/pipeline/vm/run_daily.sh $W/run_daily.sh.new && chmod +x $W/run_daily.sh.new && mv $W/run_daily.sh.new $W/run_daily.sh
for m in e1v2 daycal; do
  mkdir -p $X/ph_predict/data/shadow/$m && gsutil -q -m cp "$SRC/$m/*" $X/ph_predict/data/shadow/$m/
done
cd $X && python3 -c "
import pipeline.daily as D, json
assert 'shadow' in [s.__name__ for s in D.STEPS], 'shadow step not registered'
for m in ('e1v2', 'daycal'):
    meta = json.load(open(f'ph_predict/data/shadow/{m}/meta.json')); print(m, len(meta['models']), 'models')
print('imports ok')"
grep -q "simforecast,shadow" $W/run_daily.sh && echo "deploy ok: $TAG"
