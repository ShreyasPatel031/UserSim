#!/bin/bash
# Scratch dry run of live-code 2 for one day (default: newest data/today file). Read-only for everything live. Four scratch trees, each with its
# own HOME (forecast.py's ~/w/arm2_live and ~/w/arm3_live resolve inside it), results/ in scratch, data/ = symlink to the real data dir,
# H25_DATA = a scratch root of symlinks, features.py 033d7bd7 (the today-rows fix; live-code 2 requires it):
#   A  current forecast.py + arm2_live                       (reference)
#   B  live-code 2, no PUBLISH file                          (must equal live-code 1: arm 2 published, published_model "arm2")
#   C  live-code 2, PUBLISH file + arm3_live (e62eae24)      (arm 3 published, published_model "arm3", pred_arm2 kept as shadow)
#   D  live-code 2, PUBLISH file + an arm3_live that raises  (published_model "arm2 (arm3 failed: ...)", order = arm 2's)
set -u; W=/home/agent/w; PH=$W/experiments/ph_predict; N=$W/livecode2.new; T=$W/phops_tm/lc2; FX=$W/phops_tm/todayfix/code/features.py
D=${1:-$(ls $PH/data/today | sort | tail -1 | cut -c1-10)}; rm -rf $T; mkdir -p $T; touch $T/.t0
mk() {   # $1 tree, $2 forecast.py source, $3 h25_live source or -, $4 extra (input_guard.py) or -, $5 arm3 mode: none | real | broken
  X=$T/$1; mkdir -p $X/w/arm2_live $X/ph/results $X/h25root/days
  for f in $PH/*.py; do cp $f $X/ph/; done; cp $FX $X/ph/features.py; cp $2 $X/ph/forecast.py; [ "$4" != - ] && cp $4 $X/ph/
  ln -s $(realpath $PH/data) $X/ph/data; cp $W/arm2_live/*.py $X/w/arm2_live/; [ "$3" != - ] && cp $3 $X/w/arm2_live/h25_live.py
  H=$W/h25/data
  for e in $(ls $H); do if [ "$e" = days ]; then for f in $(ls $H/days); do ln -s $(realpath $H/days/$f) $X/h25root/days/$f; done; elif [ "$e" != today ]; then ln -s $(realpath $H/$e) $X/h25root/$e; fi; done
  if [ "$5" != none ]; then mkdir -p $X/w/arm3_live/cache; cp $W/phops_arm3/arm3_feats.py $W/phops_arm3/history_retrain.py $W/phops_arm3/ctrl.py $W/phops_arm3/honest.py $X/w/arm3_live/ 2>/dev/null
    cp $W/phops_arm3/cache/arm3_emb.npz $X/w/arm3_live/cache/; touch $X/w/arm3_live/PUBLISH
    if [ "$5" = real ]; then cp $N/arm3_live.py $X/w/arm3_live/; else printf 'def predict(day):\n    raise RuntimeError("forced arm-3 failure (dry run D)")\n' > $X/w/arm3_live/arm3_live.py; fi; fi
}
mk A $PH/forecast.py - - none; mk B $N/forecast.py $N/h25_live.py $N/input_guard.py none
mk C $N/forecast.py $N/h25_live.py $N/input_guard.py real; mk D $N/forecast.py $N/h25_live.py $N/input_guard.py broken
run() { X=$T/$1; (cd $X/ph && env -i HOME=$X PATH=/opt/exp/bin:/usr/bin:/bin TZ=America/Los_Angeles CLOUDSDK_CONFIG=/home/agent/.config/gcloud \
  HF_HOME=/home/agent/.cache/huggingface H25_DATA=$X/h25root H25_SRC=$W/ph_history/2025 PYTHONPATH=$W/mk LGB_THREADS=3 nice /opt/exp/bin/python3 forecast.py $D > $X/run.log 2>&1; echo "rc=$?" >> $X/run.log); }
for X in A B C D; do run $X; echo "$X: $(grep -h "published model" $T/$X/run.log | cut -c1-230) | $(tail -1 $T/$X/run.log)"; done
/opt/exp/bin/python3 - $T $D <<PY
import sys, json, pandas as pd
T, D = sys.argv[1:3]; R = {X: pd.read_parquet(f"{T}/{X}/ph/results/forecast_{D}.parquet") for X in "ABCD"}
o = lambda X: (R[X].sort_values("published_rank") if "published_rank" in R[X] else R[X]).id.astype(str).tolist()
for X in "BCD":
    F = R[X]; print(json.dumps({"tree": X, "published_model": str(F.published_model.iloc[0]) if "published_model" in F else None,
        "has_pred_arm3": "pred_arm3" in F, "arm2_filled": bool(F.pred_arm2.notna().all()), "top10_vs_A": len(set(o(X)[:10]) & set(o("A")[:10])),
        "order_equals_arm2_order": o(X) == F.sort_values(["pred_arm2", "id"], ascending=[False, True]).id.astype(str).tolist(),
        "order_equals_arm3_order": ("pred_arm3" in F) and o(X) == F.sort_values(["pred_arm3", "id"], ascending=[False, True]).id.astype(str).tolist(),
        "repro_published": json.load(open(f"{T}/{X}/ph/results/forecast_repro_{D}.json")).get("published")}))
PY
echo "real llm_* dirs modified: $(find -L $PH/data -maxdepth 1 -name 'llm_*' -newer $T/.t0 | wc -l)"
