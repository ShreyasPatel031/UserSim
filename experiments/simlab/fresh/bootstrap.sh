#!/bin/bash
# Fresh-session bootstrap: unpack the code bundles and run one nightly job.   bash bootstrap.sh {stageb|panel|explain} [D]
# (GCP credentials must already be active: the worker prompt activates them from GOOGLE_APPLICATION_CREDENTIALS_B64 as scripts/agent_env.sh does.)
set -u; B=gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/private/code; JOB=$1; shift; ROOT=${FRESH_ROOT:-/tmp/fresh}; mkdir -p $ROOT; cd $ROOT
gsutil -m -q cp $B/usersim.tar.gz $B/simharness.tar.gz $B/phops.tar.gz $B/mainwt.tar.gz $B/manifest.json . || { echo "FAIL code bundles"; exit 2; }
tar xzf usersim.tar.gz; tar xzf simharness.tar.gz; tar xzf phops.tar.gz; [ -f mainwt.tar.gz ] && tar xzf mainwt.tar.gz; echo "code: $(cat manifest.json)"
export FRESH_SIMHARNESS=$ROOT/cv FRESH_PHOPS=$ROOT/phops PU_MAINWT=$ROOT/mainwt PU_WORK=$ROOT/pu
# Python deps (fresh containers have no project venv): pinned to the versions the session pipeline runs with
BASE="pandas==3.0.5 numpy==2.5.3 pyarrow==26.0.0 scikit-learn==1.9.1 scipy==1.18.1 duckdb==2.0.0"
EXTRA="lightgbm==4.7.0 statsmodels==0.15.0 transformers==5.22.2 sentence-transformers==6.2.0 requests"
if ! python3 -c "import pandas, sklearn, duckdb" 2>/dev/null || [ "$JOB" = explain ] || [ "$JOB" = product_use ]; then
  # 1) exact session versions on Python 3.13 via uv; 2) fallback: system python, newest compatible versions (logged)
  PINNED=1; SYSPY=$(command -v python3)
  if $SYSPY -m pip install -q uv 2>/dev/null && $SYSPY -m uv venv -q -p 3.13 --python-preference managed $ROOT/venv 2>&1 | tail -2; [ -x $ROOT/venv/bin/python ]; then
    export PATH=$ROOT/venv/bin:$PATH; PIP="$SYSPY -m uv pip install -q -p $ROOT/venv/bin/python"
  else
    rm -rf $ROOT/venv; python3 -m venv --system-site-packages $ROOT/venv && export PATH=$ROOT/venv/bin:$PATH; PIP="python3 -m pip install -q"
  fi
  if ! $PIP $BASE; then echo "WARN exact pins unavailable on $(python3 --version); installing newest compatible"; PINNED=0
    $PIP $(echo $BASE | sed 's/==[^ ]*//g') || { echo "FAIL pip base"; exit 2; }; fi
  if [ "$JOB" = product_use ]; then $PIP "mcp==1.27.1" "google-genai==2.18.1" httpx || { echo "FAIL pip product_use"; exit 2; }; fi
  if [ "$JOB" = explain ] || [ "$JOB" = product_use ]; then
    $PIP torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu 2>/dev/null || $PIP torch --index-url https://download.pytorch.org/whl/cpu || $PIP torch
    $PIP $EXTRA 2>/dev/null || { PINNED=0; $PIP $(echo $EXTRA | sed 's/==[^ ]*//g') || { echo "FAIL pip extra"; exit 2; }; }
  fi
  python3 -c "import sys,pandas,numpy,sklearn,pyarrow,duckdb; print('python deps ok', sys.version.split()[0], 'pandas',pandas.__version__,'numpy',numpy.__version__,'sklearn',sklearn.__version__,'pyarrow',pyarrow.__version__,'duckdb',duckdb.__version__)"
  echo "deps_pinned=$PINNED"
fi
S=$ROOT/usersim/experiments/simlab
case "$JOB" in
  stageb)  STAGEB_WORK=$ROOT/stageb bash $S/cohort_calibration/stageb_nightly.sh "$@";;
  panel)   PANEL_WORK=$ROOT/panelwork bash $S/cohort_calibration/panel_nightly.sh "$@";;
  explain) EXPLAIN_WORK=$ROOT/explainwork bash $S/explain_fresh.sh "$@";;
  product_use) bash $S/product_use/nightly.sh "$@";;
  stack)   bash $S/stack/nightly.sh "$@";;
  *) echo "unknown job $JOB"; exit 2;;
esac
