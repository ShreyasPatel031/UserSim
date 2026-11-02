#!/bin/bash
# Swap the live simulation's person model to pna_ (popscore TIE2, trained on every earlier month; no page) on
# usersim-pipeline (as user agent). The live code keeps its pnx_ names: the slot now holds the all-months model.
# Copies files only; starts and stops nothing; safe while the hourly recorder runs. Run outside 00:05-01:00 PT.
# Staged: gs://usersim-bakeoff-347838016394/usersim_sim/deploy/<tag>/{code.tar, model_2026-11.pkl, pnx_features.json}
# usage: bash deploy_pna.sh <tag>      then check the last line says "deploy ok"
# Rollback: tar xf $W/backup_<tag>/before.tar -C $W/experiments
set -euo pipefail
TAG=${1:?tag}
SRC=gs://usersim-bakeoff-347838016394/usersim_sim/deploy/$TAG
W=/home/agent/w; X=$W/experiments
export PATH=/opt/exp/bin:$PATH
mkdir -p /tmp/deploy_$TAG $W/backup_$TAG && cd /tmp/deploy_$TAG
gsutil -q cp $SRC/code.tar . && tar tf code.tar | sed 's#^experiments/##' > files.txt
printf '%s\n' ph_predict/data/sim_models/model_2026-11.pkl ph_predict/data/pnx_features.json >> files.txt
(cd $X && while read -r f; do if [ -f "$f" ]; then echo "$f"; fi; done < /tmp/deploy_$TAG/files.txt > /tmp/deploy_$TAG/existing.txt
 tar cf $W/backup_$TAG/before.tar -T /tmp/deploy_$TAG/existing.txt)
echo "backed up $(wc -l < /tmp/deploy_$TAG/existing.txt) files to $W/backup_$TAG/before.tar"
tar xf code.tar -C $W
gsutil -q cp $SRC/model_2026-11.pkl $X/ph_predict/data/sim_models/model_2026-11.pkl
gsutil -q cp $SRC/pnx_features.json $X/ph_predict/data/pnx_features.json
cd $X && python3 -c "
import pickle, json
m = pickle.load(open('ph_predict/data/sim_models/model_2026-11.pkl', 'rb')); assert 'model' in m
d = json.load(open('ph_predict/data/pnx_features.json')); assert len(d) > 4000 and 'pnx_ev' in next(iter(d.values()))
import pipeline.sim_daily, pipeline.daily; print('imports ok', len(d))"
echo "deploy ok: $TAG"
