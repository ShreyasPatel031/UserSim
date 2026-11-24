#!/bin/bash
# Nightly structural shortlist from code on the VM (orchestrator 13:30Z Nov 24). The 02:21 PT write ran from an agent-session scheduled task;
# on Nov 24 the session's worker was down from ~10:00Z to 13:30Z, the task queued, and results/structural/2026-11-24/shortlist.json was missing
# for E5's re-rank. Now the VM's own bundle-12a runner writes it:
#   ~/w/tw12a/run.sh       208a1587 -> 8f032a1c (job case "shortlist"; DUE 01:20)
#   ~/w/tw12a/sched12a.txt 5dca79f9 -> 73c5b085 ("01:20 shortlist", retry "02:40 shortlist"; both before the 03:45 PT cut)
#   ~/w/experiments/ph_predict/structural_shortlist.py (cef1eb53, new on the VM): live <d> from the frozen 00:05 parquet; no refit;
#     SKIP_DONE=1 leaves an on-time bucket file alone.
# usage (VM, agent): bash deploy_shortlist.sh check | rehearse <day> | deploy | rollback
set -u; W=/home/agent/w; N=$(cd "$(dirname "$0")" && pwd); TW=$W/tw12a; PH=$W/experiments/ph_predict; BK=$W/backup_tw12a; PY=/opt/exp/bin/python3
m8() { [ -e "$1" ] && md5sum < "$1" | cut -c1-8 || echo none; }
R_OLD=208a1587; R_NEW=8f032a1c; S_OLD=5dca79f9; S_NEW=73c5b085; P_NEW=cef1eb53
check() {
  local ok=0
  [ "$(m8 $N/run.sh)" = $R_NEW ] || { echo "bundle run.sh $(m8 $N/run.sh) != $R_NEW"; ok=1; }
  [ "$(m8 $N/sched12a.txt)" = $S_NEW ] || { echo "bundle sched12a.txt != $S_NEW"; ok=1; }
  [ "$(m8 $N/structural_shortlist.py)" = $P_NEW ] || { echo "bundle structural_shortlist.py != $P_NEW"; ok=1; }
  [ "$(m8 $TW/run.sh)" = $R_OLD ] || { echo "installed run.sh $(m8 $TW/run.sh) != $R_OLD"; ok=1; }
  [ "$(m8 $TW/sched12a.txt)" = $S_OLD ] || { echo "installed sched12a.txt $(m8 $TW/sched12a.txt) != $S_OLD"; ok=1; }
  [ -e $PH/structural_shortlist.py ] && { echo "structural_shortlist.py already on the VM"; ok=1; }
  bash -n $N/run.sh || { echo "run.sh syntax"; ok=1; }
  return $ok
}
case "${1:-}" in
check) check && echo "CHECK OK";;
rehearse)   # the new job case end to end from scratch copies: uploads refused by a gsutil stub; log and status go to scratch
  D=${2:?day}; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; REAL=$(command -v gsutil); mkdir -p $T/bin $T/tw/logs $T/ph
  printf '%s\n' '#!/bin/bash' 'last="${@: -1}"' 'for a in "$@"; do case "$a" in cp|rsync|mv) case "$last" in gs://*) echo "DRY gsutil: upload refused" >&2; exit 0;; esac;; rm) echo "DRY gsutil: rm refused" >&2; exit 0;; esac; done' "exec $REAL \"\$@\"" > $T/bin/gsutil; chmod +x $T/bin/gsutil
  cp $N/structural_shortlist.py $T/ph/
  sed -e "s#TW=/home/agent/w/tw12a#TW=$T/tw#" -e "s#/home/agent/w/tw12a.locks#$T/locks#g" -e "s#cd /home/agent/w/experiments/ph_predict && SKIP_DONE=1#cd $T/ph \&\& SKIP_DONE=1#" -e "s#D=\$(date +%F)#D=$D#" $N/run.sh > $T/run.sh
  grep -q "cd $T/ph" $T/run.sh || { echo "rehearsal sed failed"; exit 1; }
  PATH=$T/bin:$PATH bash $T/run.sh shortlist; rc=$?
  tail -1 $T/tw/logs/$D.log | cut -c1-260
  f=$T/ph/results/structural/$D/shortlist.json
  [ $rc = 0 ] && [ -s $f ] && $PY -c "import json,sys; d=json.load(open('$f')); assert d['day']=='$D' and len(d['shortlists']['top20'])==min(20,d['n_launches']) and d['frozen_at']; print('shortlist ok:', d['n_launches'], 'launches, top20', len(d['shortlists']['top20']), 'frozen_at', d['frozen_at'], 'model', d['model_version'])" \
    && echo "REHEARSAL PASSED" || { echo "REHEARSAL FAILED rc=$rc"; exit 1; };;
deploy)
  H=$(TZ=America/Los_Angeles date +%H%M); { [ "$H" -ge 2330 ] || [ "$H" -lt 100 ]; } && { echo "refused: 23:30-01:00 PT"; exit 1; }
  check || { echo "refused: check failed"; exit 1; }
  mkdir -p $BK && cp -p $TW/run.sh $BK/run.sh.$R_OLD && cp -p $TW/sched12a.txt $BK/sched12a.txt.$S_OLD || exit 1
  cp $N/structural_shortlist.py $PH/structural_shortlist.py && cp $N/run.sh $TW/run.sh.new && mv $TW/run.sh.new $TW/run.sh && cp $N/sched12a.txt $TW/sched12a.txt.new && mv $TW/sched12a.txt.new $TW/sched12a.txt
  echo "DEPLOYED run.sh $(m8 $TW/run.sh), sched12a.txt $(m8 $TW/sched12a.txt), structural_shortlist.py $(m8 $PH/structural_shortlist.py); rollback: bash $N/deploy_shortlist.sh rollback";;
rollback) cp -p $BK/run.sh.$R_OLD $TW/run.sh && cp -p $BK/sched12a.txt.$S_OLD $TW/sched12a.txt && rm -f $PH/structural_shortlist.py && echo "restored run.sh $(m8 $TW/run.sh), sched12a.txt $(m8 $TW/sched12a.txt)";;
*) echo "usage: check | rehearse <day> | deploy | rollback"; exit 64;;
esac
