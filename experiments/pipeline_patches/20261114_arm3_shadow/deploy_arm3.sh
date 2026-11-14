#!/bin/bash
# Bundle 13 arm 3 (UNDEPLOYED; each step needs Shreyas's direct word to PH ops).
#   bash deploy_arm3.sh install <this folder>   pinned modules -> ~/w/arm3_live (+ history_retrain from ~/w/arm2_live), offline model check,
#                                                E5's tests, import gates, cache prewarm. Shadow writes then come from bundle 12's arm3_shadow job.
#   bash deploy_arm3.sh publish                  creates ~/w/arm3_live/PUBLISH: the 00:05 forecast publishes pred_arm3 (forecast.py with
#                                                forecast_publish_switch.patch must be deployed first); arm 2 stays as shadow column.
#   bash deploy_arm3.sh unpublish                removes PUBLISH (back to arm 2 at the next 00:05). Always allowed.
#   bash deploy_arm3.sh rollback                 unpublish + moves ~/w/arm3_live to a backup. Always allowed.
set -euo pipefail
W=/home/agent/w; A=$W/arm3_live; BK=$W/backup_arm3; mkdir -p $BK; export PATH=/opt/exp/bin:$PATH HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
STAMP=$(date -u +%Y%m%dT%H%M%S); M=${1:?install|publish|unpublish|rollback}
case "$M" in
unpublish) rm -f $A/PUBLISH; echo "arm 3 unpublished (arm 2 publishes at the next 00:05)"; exit 0;;
rollback)  rm -f $A/PUBLISH; [ -d $A ] && mv $A $BK/arm3_live.removed_$STAMP; echo "arm 3 rolled back"; exit 0;;
esac
H=$(TZ=America/Los_Angeles date +%H%M); [ "$H" -lt 0005 ] || [ "$H" -ge 0100 ] || { echo "inside 00:05-01:00 PT: not deploying"; exit 1; }
[ "$(id -un)" = agent ] || { echo "run as user agent"; exit 1; }
gate() { echo "gate: $1"; (eval "$2") || { echo "gate failed: $1: not deploying"; exit 1; }; }
if [ "$M" = publish ]; then
  [ -f $A/arm3_live.py ] || { echo "arm3_live not installed"; exit 1; }
  grep -q "ARM 3 PUBLISH SWITCH" $W/experiments/ph_predict/forecast.py || { echo "forecast.py lacks the publish switch patch: not publishing"; exit 1; }
  gate "pipeline forecast.py imports (arm 2 + arm 3 branches)" "cd $W/experiments/ph_predict && env -u PYTHONPATH /opt/exp/bin/python3 $A/import_gate.py forecast.py && env -u PYTHONPATH /opt/exp/bin/python3 -c 'import sys; sys.path.insert(0, \"$A\"); sys.path.insert(0, \".\"); import arm3_live'"
  touch $A/PUBLISH; echo "arm 3 PUBLISH set $(date -u +%FT%TZ)"; exit 0
fi
S=${2:?folder}; m() { md5sum < "$1" | cut -c1-8; }
declare -A WANT=( [arm3_feats.py]=8cfe9192 [arm3_live.py]=ad2fab6a [test_arm3_feats.py]=1a418cbf [arm3_shadow_run.py]=29d6809e [import_gate.py]=be4891b9 )
for f in "${!WANT[@]}"; do [ "$(m $S/$f)" = "${WANT[$f]}" ] || { echo "$f md5 $(m $S/$f) != ${WANT[$f]}"; exit 1; }; done
N=$W/arm3_live.stage; rm -rf /home/agent/w/arm3_live.stage; mkdir -p $N/cache $N/results
for f in "${!WANT[@]}"; do cp $S/$f $N/$f; done; cp $W/arm2_live/history_retrain.py $W/arm2_live/ctrl.py $W/arm2_live/honest.py $N/   # pinned copies, as arm2_live (Nov 14 ctrl miss)
[ -f $A/cache/arm3_emb.npz ] && cp $A/cache/arm3_emb.npz $N/cache/
gate "bge-small offline at the pinned revision" "cd $N && env -u PYTHONPATH /opt/exp/bin/python3 -c 'import arm3_feats as A; e = A.embed([\"x\"]); assert e.shape == (1, 384)'"
gate "E5 tests" "cd $N && env -u PYTHONPATH /opt/exp/bin/python3 test_arm3_feats.py"
gate "shadow job imports (as tw.sh runs it)" "cd $W/experiments/ph_predict && env -u PYTHONPATH PYTHONPATH=$W/experiments/ph_predict /opt/exp/bin/python3 $N/import_gate.py $N/arm3_shadow_run.py $N/arm3_live.py"
[ -d $A ] && { rm -f $A/PUBLISH; mv $A $BK/arm3_live.prev_$STAMP; }
mv $N $A
(cd $W/experiments/ph_predict && env -u PYTHONPATH PYTHONPATH=$W/experiments/ph_predict nice -n 19 /opt/exp/bin/python3 $A/arm3_shadow_run.py prewarm $(TZ=America/Los_Angeles date +%F)) | tail -1
echo "arm 3 installed (shadow only; PUBLISH not set)"
