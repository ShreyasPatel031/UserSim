#!/bin/bash
# Calibration truth.json from code on the VM (orchestrator 11:39Z Nov 26). It was a chain of one-shot agent-session reminders that broke on Nov 24
# (session worker down), so Nov 24 and 25 were missing until backfilled at 11:38Z Nov 26. Now the VM's bundle-12a runner writes it:
#   ~/w/tw12a/run.sh       8c4805e7 -> 348ba755 (job case "truth": yesterday + the 2 days before, only where truth.json is missing)
#   ~/w/tw12a/sched12a.txt 6d2dcc76 -> 20a890d5 ("01:45 truth", retry "02:50 truth"; E5's scorecard reads it at ~03:31 PT)
#   ~/w/calib_truth/calibration_truth.py 17029750 (new; same code as the repo; Gemini 2.5 flash on Vertex with the VM account, checked HTTP 200)
# usage (VM, agent): bash deploy_truth.sh check | rehearse <day> | selftest | deploy | rollback
set -u; W=/home/agent/w; N=$(cd "$(dirname "$0")" && pwd); TW=$W/tw12a; CT=/home/agent/w/calib_truth; BK=$W/backup_tw12a; PY=/opt/exp/bin/python3
m8() { [ -e "$1" ] && md5sum < "$1" | cut -c1-8 || echo none; }
R_OLD=8c4805e7; R_NEW=348ba755; S_OLD=6d2dcc76; S_NEW=20a890d5; P1=17029750
check() { local ok=0
  [ "$(m8 $N/run.sh)" = $R_NEW ] || { echo "bundle run.sh != $R_NEW"; ok=1; }; [ "$(m8 $N/sched12a.txt)" = $S_NEW ] || { echo "bundle sched != $S_NEW"; ok=1; }
  [ "$(m8 $N/calibration_truth.py)" = $P1 ] || { echo "bundle script != $P1"; ok=1; }
  [ "$(m8 $1/run.sh)" = $R_OLD ] || { echo "installed run.sh $(m8 $1/run.sh) != $R_OLD"; ok=1; }; [ "$(m8 $1/sched12a.txt)" = $S_OLD ] || { echo "installed sched != $S_OLD"; ok=1; }
  [ -e $2 ] && { echo "$2 already exists"; ok=1; }; bash -n $N/run.sh || ok=1; return $ok; }
install() { mkdir -p $3 && cp -p $1/run.sh $3/run.sh.$R_OLD && cp -p $1/sched12a.txt $3/sched12a.txt.$S_OLD || return 1
  mkdir -p $2/tmp && cp $N/calibration_truth.py $2/ || return 1
  cp $N/run.sh $1/run.sh.new && mv $1/run.sh.new $1/run.sh && cp $N/sched12a.txt $1/sched12a.txt.new && mv $1/sched12a.txt.new $1/sched12a.txt; }
restore() { cp -p $3/run.sh.$R_OLD $1/run.sh && cp -p $3/sched12a.txt.$S_OLD $1/sched12a.txt && rm -rf "$2"; }
case "${1:-}" in
check) check $TW $CT && echo "CHECK OK";;
rehearse)   # the job case end to end from scratch copies for one day (TRUTH_FORCE, --dry into scratch; gsutil stub refuses uploads); compares
            # launches / comments / ranks with the bucket's existing truth.json for that day
  D=${2:?day}; Y=$(date -d "$D -1 day" +%F); T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; REAL=$(command -v gsutil); mkdir -p $T/bin $T/tw/logs $T/ct/tmp $T/dry
  printf '%s\n' '#!/bin/bash' 'last="${@: -1}"' 'for a in "$@"; do case "$a" in cp|rsync|mv) case "$last" in gs://*) [ "${@: -2:1}" = - ] && cat >/dev/null; echo "DRY gsutil: upload refused" >&2; exit 0;; esac;; rm) exit 0;; esac; done' "exec $REAL \"\$@\"" > $T/bin/gsutil; chmod +x $T/bin/gsutil
  cp $N/calibration_truth.py $T/ct/
  sed -e "s#TW=/home/agent/w/tw12a#TW=$T/tw#" -e "s#/home/agent/w/tw12a.locks#$T/locks#g" -e "s#/home/agent/w/calib_truth#$T/ct#g" -e "s#D=\$(date +%F)#D=$D#" $N/run.sh > $T/run.sh
  grep -q "cd $T/ct" $T/run.sh || { echo "rehearsal sed failed"; exit 1; }
  PATH=$T/bin:$PATH TRUTH_FORCE=1 TRUTH_K=1 TRUTH_DRY=$T/dry bash $T/run.sh truth; rc=$?
  tail -1 $T/tw/logs/$D.log | cut -c1-300
  $REAL cat gs://usersim-bakeoff-347838016394/usersim_sim/results/calibration/$Y/truth.json > $T/live.json 2>/dev/null
  [ $rc = 0 ] && [ -s $T/dry/$Y/truth.json ] && $PY - $T/dry/$Y/truth.json $T/live.json <<'PYE' && echo "REHEARSAL PASSED" || { echo "REHEARSAL FAILED rc=$rc"; exit 1; }
import json, sys, re
a = json.load(open(sys.argv[1])); t = open(sys.argv[1]).read(); L = a["by_launch"]
try: b = json.load(open(sys.argv[2]))["by_launch"]
except Exception: b = None
assert L and not re.search(r"(?<![\w.])@[A-Za-z0-9_]{2,}", t), "empty or handles present"
same = b is not None and set(L) == set(b) and all(L[i].get("final_daily_rank") == b[i].get("final_daily_rank") for i in L)
print("dry launches", len(L), "| same launch set and final ranks as the bucket file:", same)
assert b is None or same
PYE
  ;;
selftest) T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; mkdir -p $T/tw; cp -p $TW/run.sh $TW/sched12a.txt $T/tw/; check $T/tw $T/ct >/dev/null || { echo "selftest: base mismatch"; exit 1; }
  install $T/tw $T/ct $T/bk || exit 1; a="$(m8 $T/tw/run.sh) $(m8 $T/tw/sched12a.txt) $(m8 $T/ct/calibration_truth.py)"
  restore $T/tw $T/ct $T/bk; b="$(m8 $T/tw/run.sh) $(m8 $T/tw/sched12a.txt) $([ -e $T/ct ] && echo present || echo gone)"
  [ "$a" = "$R_NEW $S_NEW $P1" ] && [ "$b" = "$R_OLD $S_OLD gone" ] && echo "SELFTEST OK: deploy -> $a; rollback -> $b" || { echo "SELFTEST FAILED: $a / $b"; exit 1; };;
deploy) H=$(TZ=America/Los_Angeles date +%H%M); { [ "$H" -ge 2330 ] || [ "$H" -lt 100 ]; } && { echo "refused: 23:30-01:00 PT"; exit 1; }
  check $TW $CT || { echo "refused: check failed"; exit 1; }; install $TW $CT $BK || exit 1
  echo "DEPLOYED run.sh $(m8 $TW/run.sh), sched12a.txt $(m8 $TW/sched12a.txt), calib_truth $(m8 $CT/calibration_truth.py); rollback: bash $N/deploy_truth.sh rollback";;
rollback) restore $TW $CT $BK && echo "restored run.sh $(m8 $TW/run.sh), sched12a.txt $(m8 $TW/sched12a.txt); calib_truth removed";;
*) echo "usage: check | rehearse <day> | selftest | deploy | rollback"; exit 64;;
esac
