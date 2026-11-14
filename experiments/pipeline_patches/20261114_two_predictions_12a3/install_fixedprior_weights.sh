#!/bin/bash
# "Install the fixed-prior hybrid weights" (orchestrator / E5 20:21Z Nov 14): a scripted step, never a manual file swap.
# Refuses unless the today-rows marker (~/w/today_rows_fix.json) exists. Deploys bundle 12a.3 from this folder (two_predictions.py eaa4e1f4 with
# the fixed-prior labels + hybrid_vmonly_P345_20261114.json b8a59cdd) through deploy_b12a.sh (atomic flip; rollback = previous tree), then
# writes ~/w/tw12a.d/weights_pin = b8a59cdd so any later 12a redeploy that carries other weights refuses instead of silently reverting.
# usage (on the VM, as agent): bash install_fixedprior_weights.sh <this folder>     undo: bash <folder>/deploy_b12a.sh rollback && rm ~/w/tw12a.d/weights_pin
set -euo pipefail
W=/home/agent/w; S=${1:?folder}
[ "$(id -un)" = agent ] || { echo "run as user agent"; exit 1; }
[ -s $W/today_rows_fix.json ] || { echo "today-rows marker missing: the fixed-prior weights assume a fixed 00:05 prior; not installing"; exit 1; }
[ "$(md5sum < $S/hybrid_vmonly_P345_20261114.json | cut -c1-8)" = b8a59cdd ] || { echo "weights file in $S is not b8a59cdd"; exit 1; }
bash $S/deploy_b12a.sh $S
mkdir -p $W/tw12a.d && echo b8a59cdd > $W/tw12a.d/weights_pin
echo "fixed-prior weights live: $(md5sum < $W/tw12a/hybrid_vmonly_P345_20261114.json | cut -c1-8); pin written"
