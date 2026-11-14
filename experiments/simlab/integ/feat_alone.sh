#!/bin/bash
# night $1 with: forecast.py = live (phops ph_predict 61538501), h25_live = live (e3af37b4), features = $2 (old|new)
set -u; d=$1; v=$2; SP=/tmp/claude-0/-home-user-UserSim/d06a24f8-55f2-52b0-9f28-1e7e4ec267d8/scratchpad; T=$SP/fa/${d}_$v; rm -rf $T; mkdir -p $T/code $T/root/days $T/root/today $T/home/w/arm2_live $T/h25data
cp $SP/phops/experiments/ph_predict/*.py $T/code/; cp $SP/a2rb/code/*.py $T/code/; cp $SP/phops/experiments/ph_predict/forecast.py $T/code/
[ $v = new ] && cp $SP/phops/experiments/pipeline_patches/20261114_today_rows/features.py $T/code/ || cp $SP/a2rb/code/features.py $T/code/
cp $SP/a2rb/code/h25_live.py $SP/a2rb/code/history_retrain.py $T/home/w/arm2_live/
R=$SP/a2rb/ph_predict_data
for e in $(ls $R); do case $e in days|today|build_cache*) ;; *) ln -s $R/$e $T/root/$e;; esac; done
for f in $R/days/*.json; do b=$(basename $f .json); [[ "$b" < "$d" ]] && ln -s $f $T/root/days/; done
for f in $R/today/*.json; do b=$(basename $f .json); [[ "$b" < "$d" || "$b" == "$d" ]] && ln -s $f $T/root/today/; done
ln -s $T/root $T/code/data; mkdir -p $T/code/results
cd $T/code && HOME=$T/home H25_DATA=$T/h25data H25_SRC=$SP/rb/h25src LGB_THREADS=4 HF_HUB_OFFLINE=1 timeout 1800 python forecast.py $d > $T/run.log 2>&1; echo "$d $v rc=$? md5 features $(md5sum < $T/code/features.py | cut -c1-8) | $(grep -i 'published model' $T/run.log | tail -1)"
