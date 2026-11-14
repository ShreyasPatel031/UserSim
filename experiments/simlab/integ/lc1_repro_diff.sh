#!/bin/bash
# night $1, variant $2: A = live forecast/h25_live (+features 033d7bd7); B = live-code 1; Bnr = live-code 1 with the repro hunk reverted
# (no (day,id) sort, no deterministic/force_row_wise; n_jobs=M.N_JOBS). Local: llm.run_day replaced by a raise (no Gemini), GUARD_NO_UPLOAD=1.
set -u; d=$1; v=$2; SP=/tmp/claude-0/-home-user-UserSim/d06a24f8-55f2-52b0-9f28-1e7e4ec267d8/scratchpad; LC=$SP/phops/experiments/pipeline_patches/20261114_livecode_1
T=$SP/lc1/${d}_$v; rm -rf $T; mkdir -p $T/code $T/root/days $T/root/today $T/home/w/arm2_live $T/h25data
cp $SP/phops/experiments/ph_predict/*.py $T/code/; cp $SP/a2rb/code/*.py $T/code/; cp $SP/phops/experiments/pipeline_patches/20261114_today_rows/features.py $T/code/
cp $SP/a2rb/code/history_retrain.py $T/home/w/arm2_live/
if [ $v = A ]; then cp $SP/phops/experiments/ph_predict/forecast.py $T/code/; cp $SP/a2rb/code/h25_live.py $T/home/w/arm2_live/
else cp $LC/forecast.py $LC/input_guard.py $T/code/; cp $LC/h25_live.py $T/home/w/arm2_live/
  sed -i 's/^\( *\)llm.run_day(.*$/\1raise RuntimeError("E5 local run: no Gemini")/; s/^LLM_BACKOFF = .*/LLM_BACKOFF = (0,)/' $T/code/input_guard.py
  if [ $v = Bnr ]; then
    sed -i 's/^tr = tr.sort_values(\["day", "id"\], kind="stable"); te = te.sort_values(\["day", "id"\], kind="stable")$/pass  # E5: repro sort reverted/; s/deterministic=True, force_row_wise=True, n_jobs=RJ, /n_jobs=M.N_JOBS, /' $T/code/forecast.py
    sed -i 's/^    tr = tr.sort_values(\["day", "id"\], kind="stable"); te = te.sort_values(\["day", "id"\], kind="stable")$/    pass  # E5: repro sort reverted/; s/\*\*P_, \*\*P_DET)/n_jobs=M.N_JOBS, **P_)/; s/for s in range(REPRO_SEEDS)\]/for s in range(5)]/' $T/home/w/arm2_live/h25_live.py
    grep -c "repro sort reverted" $T/code/forecast.py $T/home/w/arm2_live/h25_live.py; grep -c "P_DET)\|deterministic=True" $T/code/forecast.py $T/home/w/arm2_live/h25_live.py
  fi; fi
R=$SP/a2rb/ph_predict_data
for e in $(ls $R); do case $e in days|today|build_cache*) ;; *) ln -s $R/$e $T/root/$e;; esac; done
for f in $R/days/*.json; do b=$(basename $f .json); [[ "$b" < "$d" ]] && ln -s $f $T/root/days/; done
for f in $R/today/*.json; do b=$(basename $f .json); [[ "$b" < "$d" || "$b" == "$d" ]] && ln -s $f $T/root/today/; done
ln -s $T/root $T/code/data; mkdir -p $T/code/results
cd $T/code && GUARD_NO_UPLOAD=1 HOME=$T/home H25_DATA=$T/h25data H25_SRC=$SP/rb/h25src LGB_THREADS=4 HF_HUB_OFFLINE=1 timeout 1800 python forecast.py $d > $T/run.log 2>&1; echo "$d $v rc=$? | $(grep -i 'published model\|no line-up' $T/run.log | tail -1 | cut -c1-120)"
