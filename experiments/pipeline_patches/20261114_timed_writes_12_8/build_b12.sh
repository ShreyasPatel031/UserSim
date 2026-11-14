#!/bin/bash
# Builds the bundle-12 code tarball from pinned commits (run in a checkout of the repo, not on the VM) and uploads it to
# gs://.../deploy/b12/. Prints the tarball md5 for B12_MD5. Contents (no data, no credentials):
#   experiments/ph_predict/*.py + results/frozen/ + results/web/forward_lines.json + small results/*.json the scripts read
#   experiments/pipeline/*.py (warehouse reader)
#   h25/  h25_shadow.py history_retrain.py readable_shadow.py readable_model.py (as run today from ~/w/h25)
#   e5/e5why  E5 claude/person-model-v2 @ fcbcd617 (why_writer), .pin
#   e5/e5wt   E5 claude/person-model-v2 @ 4e4dd4e9 (team_shadow), .pin
#   e5/e5f/follow_shadow.py  @ 3c399c39
# usage: bash build_b12.sh <commit of this branch>
set -euo pipefail
C=${1:?commit}; R=$(git rev-parse --show-toplevel); O=$(mktemp -d); B=gs://usersim-bakeoff-347838016394/usersim_sim
git -C $R fetch -q origin claude/person-model-v2
mkdir -p $O/tw/experiments $O/tw/h25 $O/tw/e5/e5why $O/tw/e5/e5wt $O/tw/e5/e5f
git -C $R archive $C experiments/pipeline experiments/__init__.py 2>/dev/null | tar x -C $O/tw || git -C $R archive $C experiments/pipeline | tar x -C $O/tw
git -C $R archive $C experiments/ph_predict | tar x -C $O/tw --wildcards 'experiments/ph_predict/*.py' 'experiments/ph_predict/*.sh' 'experiments/ph_predict/results/frozen/*' \
  'experiments/ph_predict/results/web/forward_lines.json' 'experiments/ph_predict/results/*.json' 'experiments/ph_predict/results/*.jsonl' 2>/dev/null || true
for f in h25_shadow.py history_retrain.py readable_shadow.py readable_model.py; do cp $O/tw/experiments/ph_predict/$f $O/tw/h25/; done
git -C $R archive fcbcd617 experiments/simlab experiments/pipeline | tar x -C $O/tw/e5/e5why; echo fcbcd617 > $O/tw/e5/e5why/.pin
git -C $R archive 4e4dd4e9 experiments/simlab experiments/pipeline | tar x -C $O/tw/e5/e5wt; echo 4e4dd4e9 > $O/tw/e5/e5wt/.pin
git -C $R show 3c399c39:experiments/simlab/follow_shadow.py > $O/tw/e5/e5f/follow_shadow.py
cp $(dirname "$0")/tw.sh $(dirname "$0")/tw.cron $(dirname "$0")/tick12.sh $(dirname "$0")/sched12.txt $(dirname "$0")/import_gate.py $O/tw/
echo "$C" > $O/tw/COMMIT
tar czf $O/tw_code_$C.tgz -C $O tw
M=$(md5sum < $O/tw_code_$C.tgz | cut -c1-8); S=$(du -h $O/tw_code_$C.tgz | cut -f1)
[ "${NOUPLOAD:-0}" = 1 ] && { cp $O/tw_code_$C.tgz ${KEEP:-.}/; echo "kept locally"; } || gsutil -q cp $O/tw_code_$C.tgz $B/deploy/b12/tw_code_$C.tgz
echo "tarball gs://.../deploy/b12/tw_code_$C.tgz md5 $M size $S"
rm -rf $O
