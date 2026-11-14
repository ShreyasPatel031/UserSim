#!/bin/bash
# End-to-end dry run of the patched forecast.py + h25_live on a private root for night $1, today/ as the VM held it (all files <= $1, or < $1 if $2=missing)
set -u; d=$1; mode=${2:-present}; T=/tmp/claude-0/-home-user-UserSim/d06a24f8-55f2-52b0-9f28-1e7e4ec267d8/scratchpad/e2e/${d}_${mode}; rm -rf $T; mkdir -p $T/code $T/root/days $T/root/today $T/home/w/arm2_live $T/h25data
cp /tmp/claude-0/-home-user-UserSim/d06a24f8-55f2-52b0-9f28-1e7e4ec267d8/scratchpad/phops/experiments/ph_predict/*.py $T/code/; cp /tmp/claude-0/-home-user-UserSim/d06a24f8-55f2-52b0-9f28-1e7e4ec267d8/scratchpad/a2rb/code/*.py $T/code/; cp /tmp/claude-0/-home-user-UserSim/d06a24f8-55f2-52b0-9f28-1e7e4ec267d8/scratchpad/phops/experiments/pipeline_patches/20261114_today_rows/features.py /tmp/claude-0/-home-user-UserSim/d06a24f8-55f2-52b0-9f28-1e7e4ec267d8/scratchpad/phops/experiments/pipeline_patches/20261114_today_rows/forecast.py $T/code/
cp /tmp/claude-0/-home-user-UserSim/d06a24f8-55f2-52b0-9f28-1e7e4ec267d8/scratchpad/phops/experiments/pipeline_patches/20261114_today_rows/h25_live.py $T/home/w/arm2_live/; cp /tmp/claude-0/-home-user-UserSim/d06a24f8-55f2-52b0-9f28-1e7e4ec267d8/scratchpad/a2rb/code/history_retrain.py $T/home/w/arm2_live/
R=/tmp/claude-0/-home-user-UserSim/d06a24f8-55f2-52b0-9f28-1e7e4ec267d8/scratchpad/a2rb/ph_predict_data
for e in $(ls $R); do case $e in days|today|build_cache*) ;; *) ln -s $R/$e $T/root/$e;; esac; done
for f in $R/days/*.json; do b=$(basename $f .json); [[ "$b" < "$d" ]] && ln -s $f $T/root/days/; done
for f in $R/today/*.json; do b=$(basename $f .json); if [ "$mode" = missing ]; then [[ "$b" < "$d" ]] && ln -s $f $T/root/today/; else [[ "$b" < "$d" || "$b" == "$d" ]] && ln -s $f $T/root/today/; fi; done
ln -s $T/root $T/code/data; mkdir -p $T/code/results
cd $T/code && HOME=$T/home H25_DATA=$T/h25data H25_SRC=/tmp/claude-0/-home-user-UserSim/d06a24f8-55f2-52b0-9f28-1e7e4ec267d8/scratchpad/rb/h25src LGB_THREADS=4 HF_HUB_OFFLINE=1 timeout 1500 python forecast.py $d > $T/run.log 2>&1; echo "rc=$?"
ls $T/code/results/ | head; grep -E "published model|no line-up|Error|Traceback" $T/run.log | head -5
