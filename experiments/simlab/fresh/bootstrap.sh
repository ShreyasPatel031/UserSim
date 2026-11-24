#!/bin/bash
# Fresh-session bootstrap: unpack the code bundles and run one nightly job.   bash bootstrap.sh {stageb|panel|explain} [D]
# (GCP credentials must already be active: the worker prompt activates them from GOOGLE_APPLICATION_CREDENTIALS_B64 as scripts/agent_env.sh does.)
set -u; B=gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/private/code; JOB=$1; shift; ROOT=${FRESH_ROOT:-/tmp/fresh}; mkdir -p $ROOT; cd $ROOT
gsutil -m -q cp $B/usersim.tar.gz $B/simharness.tar.gz $B/phops.tar.gz $B/manifest.json . || { echo "FAIL code bundles"; exit 2; }
tar xzf usersim.tar.gz; tar xzf simharness.tar.gz; tar xzf phops.tar.gz; echo "code: $(cat manifest.json)"
export FRESH_SIMHARNESS=$ROOT/cv FRESH_PHOPS=$ROOT/phops
S=$ROOT/usersim/experiments/simlab
case "$JOB" in
  stageb)  STAGEB_WORK=$ROOT/stageb bash $S/cohort_calibration/stageb_nightly.sh "$@";;
  panel)   PANEL_WORK=$ROOT/panelwork bash $S/cohort_calibration/panel_nightly.sh "$@";;
  explain) EXPLAIN_WORK=$ROOT/explainwork bash $S/explain_fresh.sh "$@";;
  *) echo "unknown job $JOB"; exit 2;;
esac
