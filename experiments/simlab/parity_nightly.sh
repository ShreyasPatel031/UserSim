#!/bin/bash
# Nightly live-vs-backtest parity for arm 2 (orchestrator 19:16Z Nov 14). Checks the PT day that just closed (D = yesterday PT).
# Needs: raw/daily/<D>/today_0005.json (the 00:05 list the live model read; published nightly) and the FINAL list for D at
# raw/daily/<D>/days_final_<D>.json (NOT published yet: PH ops would add one upload of the VM's data/days/<D>.json). Without the final
# list the night is logged "skipped" (no alert). Final lists accumulate in $SP/parity_data/days so later nights see the history.
# Writes $SP/parity/<D>.json; prints "PARITY ALERT <D> ..." only for a NEW kind of difference (parity_rules.py).
#    bash parity_nightly.sh <scratchpad> [day]
set -u; SP=$1; HERE="$(cd "$(dirname "$0")" && pwd)"; B=gs://usersim-bakeoff-347838016394/usersim_sim/raw/daily
D=${2:-$(TZ=America/Los_Angeles date -d yesterday +%F)}; DATA=$SP/parity_data; CODE=$SP/parity_code; mkdir -p $SP/parity
[ -d $DATA ] || cp -rL $SP/a2rb/ph_predict_data $DATA
cp $HERE/parity_check.py $HERE/parity_rules.py $CODE/
gsutil -q cp $B/$D/today_0005.json $DATA/today/$D.json || { echo "parity $D skipped: no today_0005.json"; exit 0; }
[ -s $DATA/days/$D.json ] || gsutil -q cp $B/$D/days_final_$D.json $DATA/days/$D.json 2>/dev/null || { rm -f $DATA/days/$D.json; echo "parity $D skipped: no final list (raw/daily/$D/days_final_$D.json not published)"; exit 0; }
(cd $CODE && timeout 1500 python parity_check.py $CODE $DATA $SP/rb/h25src $D $SP/parity/$D.json > $SP/parity/$D.log 2>&1); rc=$?
st=$(python -c "import json;r=json.load(open('$SP/parity/$D.json'));print(r['status'], list(r['UNEXPECTED differing columns']))" 2>/dev/null || echo "no output")
if [ $rc = 1 ]; then echo "PARITY ALERT $D $st"; elif [ $rc = 0 ]; then echo "parity $D $st"; else echo "PARITY ALERT $D check failed rc=$rc (see $SP/parity/$D.log)"; fi
