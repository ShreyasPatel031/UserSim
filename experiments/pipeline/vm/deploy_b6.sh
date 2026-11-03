#!/bin/bash
# Bundle 6 (trial forecast only, standing rule 2): installs the shadow model honest_a2 (live offset + day terms + A1 team
# history + A2 team comments in the 7 / 14 days before) and adds it to the default SHADOW_MODELS ("daycal,honest_a2").
# Written to `forecasts` as shadow_honest_a2 and scored by `score`; not published. The headline forecast is unchanged
# (no model.py). The package (models, meta, predict.py, team_history.jsonl with usernames) comes from the bucket only.
# Copies files only; starts and stops nothing. Run outside 00:05-01:00 PT.
# usage: bash deploy_b6.sh <dir with experiments/...>
# Rollback: tar xf $W/backup_b6/before.tar -C $W/experiments; rm -rf $W/experiments/ph_predict/data/shadow/honest_a2
set -euo pipefail
SRC=${1:?dir}; W=/home/agent/w; X=$W/experiments
PKG=gs://usersim-bakeoff-347838016394/usersim_sim/tmp/ph_ops/shadow_honest_a2
export PATH=/opt/exp/bin:$PATH
test ! -e $X/ph_predict/data/shadow/honest_a2 || { echo "honest_a2 already installed"; exit 1; }
mkdir -p $W/backup_b6
(cd $X && tar cf $W/backup_b6/before.tar pipeline/daily.py)
echo "backed up pipeline/daily.py to $W/backup_b6/"
mkdir -p $X/ph_predict/data/shadow/honest_a2.new
gsutil -q cp "$PKG/*" $X/ph_predict/data/shadow/honest_a2.new/
cmp $SRC/experiments/ph_predict/shadow_pkgs/honest_a2/predict.py $X/ph_predict/data/shadow/honest_a2.new/predict.py
mv $X/ph_predict/data/shadow/honest_a2.new $X/ph_predict/data/shadow/honest_a2
cp $SRC/experiments/pipeline/daily.py $X/pipeline/daily.py.new && mv $X/pipeline/daily.py.new $X/pipeline/daily.py
cd $X && python3 -c "
import pipeline.daily as D
names = [s.__name__ for s in D.STEPS]
assert names.index('shadow') < names.index('score'), names
assert D.SHADOW_DEFAULT == 'daycal,honest_a2', D.SHADOW_DEFAULT
print('imports ok')"
grep -q "simforecast,shadow" $W/run_daily.sh && echo "deploy ok: b6"
