#!/bin/bash
# Fresh-session bootstrap: unpack the code bundles and run one nightly job.   bash bootstrap.sh {stageb|panel|explain} [D]
# (GCP credentials must already be active: the worker prompt activates them from GOOGLE_APPLICATION_CREDENTIALS_B64 as scripts/agent_env.sh does.)
set -u; B=gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/private/code; JOB=$1; shift; ROOT=${FRESH_ROOT:-/tmp/fresh}; mkdir -p $ROOT; cd $ROOT
gsutil -m -q cp $B/usersim.tar.gz $B/simharness.tar.gz $B/phops.tar.gz $B/manifest.json . || { echo "FAIL code bundles"; exit 2; }
tar xzf usersim.tar.gz; tar xzf simharness.tar.gz; tar xzf phops.tar.gz; echo "code: $(cat manifest.json)"
export FRESH_SIMHARNESS=$ROOT/cv FRESH_PHOPS=$ROOT/phops
# Python deps (fresh containers have no project venv): pinned to the versions the session pipeline runs with
BASE="pandas==3.0.5 numpy==2.5.3 pyarrow==26.0.0 scikit-learn==1.9.1 scipy==1.18.1 duckdb==2.0.0"
EXTRA="lightgbm==4.7.0 statsmodels==0.15.0 transformers==5.22.2 sentence-transformers==6.2.0 requests"
if ! python3 -c "import pandas, sklearn, duckdb" 2>/dev/null || [ "$JOB" = explain ]; then
  python3 -m venv --system-site-packages $ROOT/venv && export PATH=$ROOT/venv/bin:$PATH
  python3 -m pip install -q $BASE || { echo "FAIL pip base"; exit 2; }
  if [ "$JOB" = explain ]; then python3 -m pip install -q torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu || python3 -m pip install -q torch; python3 -m pip install -q $EXTRA || { echo "FAIL pip extra"; exit 2; }; fi
  python3 -c "import pandas, sklearn; print('python deps ok', pandas.__version__)"
fi
S=$ROOT/usersim/experiments/simlab
case "$JOB" in
  stageb)  STAGEB_WORK=$ROOT/stageb bash $S/cohort_calibration/stageb_nightly.sh "$@";;
  panel)   PANEL_WORK=$ROOT/panelwork bash $S/cohort_calibration/panel_nightly.sh "$@";;
  explain) EXPLAIN_WORK=$ROOT/explainwork bash $S/explain_fresh.sh "$@";;
  *) echo "unknown job $JOB"; exit 2;;
esac
