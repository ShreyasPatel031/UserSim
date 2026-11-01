#!/bin/bash
# Deploy the daily simulation forecast and the leaderboard cross-check to usersim-pipeline (as user agent).
# Safe while the hourly recorder runs: it only copies files and installs packages; it starts and stops nothing.
# Staged inputs: gs://usersim-bakeoff-347838016394/usersim_sim/deploy/<tag>/{code.tar, model_2026-11.pkl, pnx_features.json, emb.npz}
# usage: bash deploy_sim.sh <tag>      then check the last line says "deploy ok"
set -euo pipefail
TAG=${1:?tag}
SRC=gs://usersim-bakeoff-347838016394/usersim_sim/deploy/$TAG
W=/home/agent/w; X=$W/experiments
export PATH=/opt/exp/bin:$PATH
# 1. packages for launch embeddings (bge-small, CPU only; about 1 GB on disk)
python3 -c "import sentence_transformers" 2>/dev/null || {
  pip install -q torch --index-url https://download.pytorch.org/whl/cpu
  pip install -q sentence-transformers
}
# 2. code (backup of every file it replaces under $W/backup_<tag>/)
mkdir -p /tmp/deploy_$TAG $W/backup_$TAG && cd /tmp/deploy_$TAG
gsutil -q cp $SRC/code.tar . && tar tf code.tar > files.txt
(cd $X && tar cf $W/backup_$TAG/before.tar --ignore-failed-read $(sed 's#^experiments/##' files.txt | grep -v '^pipeline/vm/run_daily.sh$') 2>/dev/null || true)
cp $W/run_daily.sh $W/backup_$TAG/run_daily.sh
tar xf code.tar -C $W                       # code.tar paths start with experiments/
cp $X/pipeline/vm/run_daily.sh $W/run_daily.sh
# 3. model, backtest simulation rows, embeddings
mkdir -p $X/ph_predict/data/sim_models $X/ph_predict/data/sim_live
gsutil -q cp $SRC/model_2026-11.pkl $X/ph_predict/data/sim_models/
gsutil -q cp $SRC/pnx_features.json $X/ph_predict/data/pnx_features.json
gsutil -q cp $SRC/emb.npz $X/ph_predict/data/sim_live/emb.npz
# 4. warm the embedding model cache and check imports
cd $X && python3 -c "
from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5', device='cpu')
import pipeline.sim_daily, pipeline.list_check, pipeline.daily; print('imports ok')"
grep -q "simforecast" $W/run_daily.sh && echo "deploy ok: $TAG"
