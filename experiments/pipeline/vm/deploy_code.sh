#!/bin/bash
# Deploy code-only changes to usersim-pipeline (as user agent), then run an optional one-off repair command.
# Safe while the hourly recorder runs: it only copies files; it starts and stops nothing.
# Staged input: gs://usersim-bakeoff-347838016394/usersim_sim/deploy/<tag>/code.tar (paths start with experiments/),
# optional gs://.../deploy/<tag>/post.sh (run from experiments/ after the copy).
# usage: bash deploy_code.sh <tag>      then check the last line says "deploy ok"
# Rollback: tar xf $W/backup_<tag>/before.tar -C $W/experiments; cp $W/backup_<tag>/run_daily.sh $W/run_daily.sh.new && mv $W/run_daily.sh.new $W/run_daily.sh
set -euo pipefail
TAG=${1:?tag}
SRC=gs://usersim-bakeoff-347838016394/usersim_sim/deploy/$TAG
W=/home/agent/w; X=$W/experiments
export PATH=/opt/exp/bin:$PATH
mkdir -p /tmp/deploy_$TAG $W/backup_$TAG && cd /tmp/deploy_$TAG
gsutil -q cp $SRC/code.tar . && tar tf code.tar > files.txt
(cd $X && sed 's#^experiments/##' /tmp/deploy_$TAG/files.txt | while read -r f; do if [ -f "$f" ]; then echo "$f"; fi; done > /tmp/deploy_$TAG/existing.txt
 tar cf $W/backup_$TAG/before.tar -T /tmp/deploy_$TAG/existing.txt)
echo "backed up $(wc -l < /tmp/deploy_$TAG/existing.txt) files to $W/backup_$TAG/before.tar"
cp $W/run_daily.sh $W/backup_$TAG/run_daily.sh
tar xf code.tar -C $W
if grep -q '^experiments/pipeline/vm/run_daily.sh$' files.txt; then
  cp $X/pipeline/vm/run_daily.sh $W/run_daily.sh.new && chmod +x $W/run_daily.sh.new && mv $W/run_daily.sh.new $W/run_daily.sh
fi
if gsutil -q stat $SRC/post.sh; then
  gsutil -q cp $SRC/post.sh . && (cd $X && bash /tmp/deploy_$TAG/post.sh)
fi
cd $X && python3 -c "import pipeline.daily, pipeline.list_check; print('imports ok')"
echo "deploy ok: $TAG"
