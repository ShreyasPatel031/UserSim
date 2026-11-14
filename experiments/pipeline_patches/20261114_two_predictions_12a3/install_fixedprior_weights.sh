#!/bin/bash
# "Install the fixed-prior hybrid weights" (orchestrator / E5 20:21Z Nov 14): a scripted step, never a manual file swap.
# Refuses unless the today-rows marker (~/w/today_rows_fix.json) exists. Deploys bundle 12a.3 from this folder (two_predictions.py eaa4e1f4 with
# the fixed-prior labels + hybrid_vmonly_P345_20261114.json b8a59cdd) through deploy_b12a.sh (atomic flip; rollback = previous tree), then
# writes ~/w/tw12a.d/weights_pin = b8a59cdd so any later 12a redeploy that carries other weights refuses instead of silently reverting.
# usage (on the VM, as agent): bash install_fixedprior_weights.sh <this folder>     undo: bash <folder>/deploy_b12a.sh rollback (it rewrites the pin from the restored tree)
set -euo pipefail
W=/home/agent/w; S=${1:?folder}
[ "$(id -un)" = agent ] || { echo "run as user agent"; exit 1; }
[ -s $W/today_rows_fix.json ] || { echo "today-rows marker missing: the fixed-prior weights assume a fixed 00:05 prior; not installing"; exit 1; }
[ "$(md5sum < $S/hybrid_vmonly_P345_20261114.json | cut -c1-8)" = b8a59cdd ] || { echo "weights file in $S is not b8a59cdd"; exit 1; }
# pin BEFORE the flip (E5 pre-flight 2): a kill after the flip can never leave the fixed-prior weights live without the pin; a failed
# deploy (the flip did not happen) removes the pin again unless the live tree already carries b8a59cdd
mkdir -p $W/tw12a.d && echo b8a59cdd > $W/tw12a.d/weights_pin
if ! bash $S/deploy_b12a.sh $S; then
  [ "$(md5sum < $W/tw12a/hybrid_vmonly_P345_20261114.json 2>/dev/null | cut -c1-8)" = b8a59cdd ] || rm -f $W/tw12a.d/weights_pin
  echo "deploy failed; weights pin: $(cat $W/tw12a.d/weights_pin 2>/dev/null || echo removed)"; exit 1; fi
echo "fixed-prior weights live: $(md5sum < $W/tw12a/hybrid_vmonly_P345_20261114.json | cut -c1-8); pin written"
