#!/bin/bash
# Scratch dry run of live-code 1 for one day (default: newest data/today file). Read-only for everything live:
# two scratch trees A (current forecast.py + arm2_live, features.py 033d7bd7) and B (live-code 1), each with its own HOME (so forecast.py's
# ~/w/arm2_live is the scratch copy), results/ in scratch, data/ = symlink to the real data dir, H25_DATA = a scratch root of symlinks.
# Compares the published order A vs B, checks B's repro json, guards record and parquet columns; reruns B to check bit-identical output.
# Also asserts the real llm_* dirs were not modified (mtime snapshot before / after).
set -u; W=/home/agent/w; PH=$W/experiments/ph_predict; N=$W/livecode1.new; T=$W/phops_tm/lc1; FX=$W/phops_tm/todayfix/code/features.py
D=${1:-$(ls $PH/data/today | sort | tail -1 | cut -c1-10)}; rm -rf $T; mkdir -p $T
[ "$(md5sum < $FX | cut -c1-8)" = 033d7bd7 ] || { echo "features fix copy missing"; exit 1; }
snap() { find -L $PH/data -maxdepth 1 -name "llm_*" -newer $T/.t0 2>/dev/null | wc -l; }
touch $T/.t0
mk() {   # $1 = tree name, $2 = source of forecast.py, $3 = source dir of arm2_live files, $4 = extra file (input_guard.py) or -
  X=$T/$1; mkdir -p $X/w/arm2_live $X/ph/results $X/h25root/days
  for f in $PH/*.py; do cp $f $X/ph/; done; cp $FX $X/ph/features.py; cp $2 $X/ph/forecast.py; [ "$4" != - ] && cp $4 $X/ph/
  ln -s $(realpath $PH/data) $X/ph/data; cp $W/arm2_live/*.py $X/w/arm2_live/; [ "$3" != - ] && cp $3 $X/w/arm2_live/h25_live.py
  H=$W/h25/data
  for e in $(ls $H); do if [ "$e" = days ]; then for f in $(ls $H/days); do ln -s $(realpath $H/days/$f) $X/h25root/days/$f; done; elif [ "$e" != today ]; then ln -s $(realpath $H/$e) $X/h25root/$e; fi; done
}
mk A $PH/forecast.py - -
mk B $N/forecast.py $N/h25_live.py $N/input_guard.py
run() { X=$T/$1; (cd $X/ph && env -i HOME=$X PATH=/opt/exp/bin:/usr/bin:/bin TZ=America/Los_Angeles CLOUDSDK_CONFIG=$W/../.config/gcloud \
  H25_DATA=$X/h25root H25_SRC=$W/ph_history/2025 PYTHONPATH=$W/mk LGB_THREADS=3 nice /opt/exp/bin/python3 forecast.py $D > $X/run$2.log 2>&1; echo "rc=$?" >> $X/run$2.log); }
run A 1; run B 1; cp $T/B/ph/results/forecast_$D.parquet $T/B_first.parquet; run B 2
echo "day $D"; for X in A B; do echo "$X: $(grep -h "published model" $T/$X/run1.log | cut -c1-200) | $(tail -1 $T/$X/run1.log)"; done
/opt/exp/bin/python3 - $T $D <<PY
import sys, json, hashlib, pandas as pd
T, D = sys.argv[1:3]
A = pd.read_parquet(f"{T}/A/ph/results/forecast_{D}.parquet"); B = pd.read_parquet(f"{T}/B/ph/results/forecast_{D}.parquet"); B1 = pd.read_parquet(f"{T}/B_first.parquet")
oa = A.id.astype(str).tolist(); ob = B.sort_values("published_rank").id.astype(str).tolist()
print(json.dumps({"rows_A": len(A), "rows_B": len(B), "same_order": oa == ob, "top3_same": oa[:3] == ob[:3], "top10_overlap": len(set(oa[:10]) & set(ob[:10])),
                  "first_diff_at": next((i + 1 for i, (x, y) in enumerate(zip(oa, ob)) if x != y), None),
                  "B_cols": [c for c in ("published_rank", "known") if c in B], "known_in_B": int(B.known.sum()) if "known" in B else None,
                  "B_rerun_bit_identical": bool(B.equals(B1))}))
for f in ("forecast_repro", "forecast_inputs"):
    try: print(f, json.dumps(json.load(open(f"{T}/B/ph/results/{f}_{D}.json")))[:400])
    except Exception as e: print(f, "missing", type(e).__name__)
PY
echo "real llm_* dirs modified during the run: $(snap)"
