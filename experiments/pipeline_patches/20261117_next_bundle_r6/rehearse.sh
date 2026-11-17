#!/bin/bash
# End-to-end rehearsal (orchestrator 09:54Z Nov 16: "an import gate is not a rehearsal"). Runs every CHANGED job of this bundle
# end to end on a real day from scratch copies, with DRY output: results go to a scratch dir and a gsutil stub refuses every
# upload / rm to gs:// (reads pass through). A job is "changed" when the bundle's file differs from the installed one
# (REHEARSE_ALL=1 runs every job). Exit 0 only if every job that ran exits 0.
# usage (VM, as agent): bash rehearse.sh <day YYYY-MM-DD>      called by run_chain.sh between check and deploy
set -u; W=${NB_W:-/home/agent/w}; N=$(cd "$(dirname "$0")" && pwd); D=${1:?day}; PY=/opt/exp/bin/python3
H=$(TZ=America/Los_Angeles date +%H%M); [ "$H" -ge 0005 ] && [ "$H" -lt 0100 ] && { echo "refused: 00:05-01:00 PT (pipeline run)"; exit 1; }
m8() { [ -e "$1" ] && md5sum < "$1" | cut -c1-8 || echo none; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
REAL=$(command -v gsutil); mkdir -p $T/bin
cat > $T/bin/gsutil <<STUB
#!/bin/bash
last="\${@: -1}"
for a in "\$@"; do case "\$a" in cp|rsync|mv) case "\$last" in gs://*) echo "DRY gsutil: upload to \$last refused" >&2; exit 0;; esac;; rm) echo "DRY gsutil: rm refused" >&2; exit 0;; esac; done
exec $REAL "\$@"
STUB
chmod +x $T/bin/gsutil; export PATH=$T/bin:/opt/exp/bin:$PATH
# scratch code trees: ph (pipeline experiments/ph_predict code, real data read-only via symlink, empty results), tw (12.8 code), arm2, arm3
mkp() { local src=$1 dst=$2; mkdir -p $dst; (cd $src && find . -maxdepth 1 -name '*.py' -exec cp {} $dst/ \;); [ -e $src/data ] && ln -s $src/data $dst/data; mkdir -p $dst/results
  # read inputs that jobs load from results/ (frozen models, live model json): COPIED (never symlinked: a job write must not reach the real file)
  [ -d $src/results ] && { find $src/results -maxdepth 1 -type f -exec cp {} $dst/results/ \; ; [ -d $src/results/frozen ] && cp -r $src/results/frozen $dst/results/; }; }
mkp $W/experiments/ph_predict $T/ph; cp -r $W/experiments/pipeline $T/pipeline 2>/dev/null
mkdir -p $T/tw/experiments; [ -d $W/tw ] && { mkp $W/tw/experiments/ph_predict $T/tw/experiments/ph_predict; cp -r $W/tw/experiments/pipeline $T/tw/experiments/; }
mkdir -p $T/arm2; cp $W/arm2_live/*.py $T/arm2/; mkdir -p $T/arm3; [ -d $W/arm3_live ] && { cp $W/arm3_live/*.py $T/arm3/; ln -s $W/arm3_live/cache $T/arm3/cache; mkdir -p $T/arm3/results; }
mkdir -p $T/h25; [ -d $W/tw/h25 ] && cp $W/tw/h25/*.py $T/h25/
ch() { [ "${REHEARSE_ALL:-0}" = 1 ] || [ "$(m8 $N/$1)" != "$(m8 $2)" ]; }   # bundle file vs installed
put() { cp $N/$1 $2; }
run=0; bad=0
job() { local name=$1; shift; run=$((run+1)); local out; out=$("$@" 2>&1); local rc=$?
  echo "$name rc=$rc | $(echo "$out" | grep -v 'it/s' | tail -1 | cut -c1-240)"; [ $rc = 0 ] || { bad=1; echo "$out" | tail -15; }; }
# arm 2 live (h25_live + rootlink + ctrl): full predict on day D, sidecar redirected to scratch
if ch h25_live.py $W/arm2_live/h25_live.py || ch rootlink.py $W/arm2_live/rootlink.py || ch ctrl.py $W/arm2_live/ctrl.py; then
  s=$(case $(m8 $W/arm2_live/h25_live.py) in ff40d796|88c206ce|2f49972b) echo h25_live.py;; *) echo h25_live_cur.py;; esac)
  cp $N/$s $T/arm2/h25_live.py; put rootlink.py $T/arm2/rootlink.py; put ctrl.py $T/arm2/ctrl.py
  cat > $T/arm2_run.py <<PYEOF
import json, sys, os
import h25_live as H
cap = {}
def side(d, te, cc, real):
    cap.update(rows=len(te), inputs=len(cc), null={c: round(float(te[c].isna().mean()), 4) for c in cc})
H._write_input_nulls = side
P, info = H.predict(sys.argv[1]); json.dump({"pred": P.to_dict("records"), "info": str(info), "nulls": cap}, open("$T/arm2_out.json", "w"))
print(json.dumps({"day": sys.argv[1], "launches": len(P), "inputs": cap.get("inputs"), "pred_null": int(P.pred_arm2.isna().sum())}))
PYEOF
  job arm2_live bash -c "cd $W/experiments/ph_predict && PYTHONPATH=$T/arm2:. $PY $T/arm2_run.py $D"
fi
if [ -d $W/tw ]; then
  if ch readable_shadow.py $W/tw/h25/readable_shadow.py; then put readable_shadow.py $T/h25/readable_shadow.py
    job readable_shadow bash -c "cd $T/ph && PYTHONPATH=$W/mk:. $PY $T/h25/readable_shadow.py $D"; fi
  if ch h25_shadow.py $W/tw/h25/h25_shadow.py || ch history_retrain.py $W/tw/h25/history_retrain.py; then
    put h25_shadow.py $T/h25/h25_shadow.py; put history_retrain.py $T/h25/history_retrain.py; put rootlink.py $T/h25/rootlink.py
    job h25_shadow bash -c "cd $T/ph && PYTHONPATH=$W/mk:.:$T/h25 H25_SRC=$W/ph_history/2025 $PY $T/h25/h25_shadow.py $D"; fi
  if ch arm2_shap.py $W/tw/experiments/ph_predict/arm2_shap.py; then put arm2_shap.py $T/tw/experiments/ph_predict/arm2_shap.py
    job arm2_shap bash -c "cd $T/tw/experiments/ph_predict && $PY arm2_shap.py $D"; fi
  if ch comment_forecast.py $W/tw/experiments/ph_predict/comment_forecast.py; then put comment_forecast.py $T/tw/experiments/ph_predict/comment_forecast.py
    put rootlink.py $T/tw/experiments/ph_predict/rootlink.py; mkdir -p $T/cmt
    job comment_forecast_P030 bash -c "cd $T/tw/experiments/ph_predict && CF_WORK=$T/cmt CF_MODEL_OUT=$T/cf_model.json $PY comment_forecast.py live $D P030"; fi
  if ch tw.sh $W/tw/tw.sh; then job tw_sh_syntax bash -n $N/tw.sh; fi
fi
if [ -f $W/arm3_live/arm3_live.py ] && ch arm3_live.py $W/arm3_live/arm3_live.py; then put arm3_live.py $T/arm3/arm3_live.py; put rootlink.py $T/arm3/rootlink.py
  mkdir -p $T/a3in; job arm3_shadow bash -c "cd $W/experiments/ph_predict && env -u PYTHONPATH PYTHONPATH=$W/experiments/ph_predict ARM3_INPUTS_DIR=$T/a3in HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 LGB_THREADS=2 $PY $T/arm3/arm3_shadow_run.py $D"; fi
[ -d $T/a3in ] && echo "arm3 sidecar files: $(ls $T/a3in 2>/dev/null | tr '\n' ' ')"
echo "rehearsal $D: $run job(s) run end to end (DRY: scratch output, uploads refused)"
[ $bad = 0 ] && { echo "REHEARSAL PASSED"; exit 0; } || { echo "REHEARSAL FAILED"; exit 1; }
