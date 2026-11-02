#!/bin/bash
# Bundle 3 (honest): the honest launch model and simulation forecast (model.py HONEST=1, sim_forecast.py), the at_launch step
# (makers' and hunter's PH follower counts at 00:05, table at_launch_followers, backfilled from data/today/), the day-calibrated
# weekly shadow (E1 v2 off: trained on leaky inputs), weekly scoring, the people step reading Data Feeder's daily delivery,
# forecast.py saving the raw predictions. Self-contained: includes everything in 20261102_shadow2.
# Copies files only; starts and stops nothing. Run outside 00:05-01:00 PT. Needs Shreyas's approval to run.
# Staged: gs://usersim-bakeoff-347838016394/usersim_sim/deploy/<tag>/{code.tar, daycal/*}
# usage: bash deploy_b3.sh <tag>      then check the last line says "deploy ok"
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
for m in daycal; do
  mkdir -p $X/ph_predict/data/shadow/$m && gsutil -q -m cp "$SRC/$m/*" $X/ph_predict/data/shadow/$m/
done
cd $X && python3 -c "
import pipeline.daily as D, json
assert 'shadow' in [s.__name__ for s in D.STEPS], 'shadow step not registered'
for m in ('daycal',):
    meta = json.load(open(f'ph_predict/data/shadow/{m}/meta.json')); print(m, len(meta['models']), 'models')
import sys; sys.path.insert(0, 'ph_predict'); import model as M
assert M.HONEST and M.honest_drop('fol_team') and M.honest_drop('ph_hunter_followers') and not M.honest_drop('promo_posts'), 'honest filter'
assert 'at_launch' in [s.__name__ for s in D.STEPS], 'at_launch step not registered'
print('honest filter ok'); print('imports ok')"
python3 -m pipeline.at_launch backfill
grep -q "launches,at_launch,list_check" $W/run_daily.sh && grep -q "simforecast,shadow" $W/run_daily.sh && echo "deploy ok: $TAG"
