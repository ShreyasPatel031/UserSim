#!/bin/bash
# Deploy "live-code 2" = live-code 1 + the arm-3 publish switch and the arm-3 audit fixes (UNDEPLOYED until Shreyas's direct word).
# Files staged in ~/w/livecode2.new. The arm-3 PUBLISH file is NOT created here (deploy_arm3.sh publish, separately, after E5's arm-3 night audit).
# arm3_live.py is installed only if bundle 13's ~/w/arm3_live exists (it needs arm3_feats + the bge-small cache from that bundle).
#   bash deploy_livecode1.sh check     pre-checks + import gate on the staged files + scratch dry run (dry_livecode.sh); changes nothing
#   bash deploy_livecode1.sh deploy    refuses 00:05-01:00 PT; requires the today-rows fix (features.py 033d7bd7) already live
#   bash deploy_livecode1.sh rollback  restores the three backed-up files and removes input_guard.py (always allowed)
set -uo pipefail
W=/home/agent/w; PH=$W/experiments/ph_predict; N=$W/livecode2.new; BK=$W/backup_livecode2; PY=/opt/exp/bin/python3
m8() { md5sum "$1" | cut -c1-8; }
declare -A LIVE=([$PH/forecast.py]=61538501 [$W/arm2_live/h25_live.py]=e3af37b4 [$W/experiments/pipeline/daily.py]=27f0578d)
declare -A NEW=([forecast.py]=3c7da1b5 [h25_live.py]=ff40d796 [daily.py]=54456921 [input_guard.py]=01547d5b)
declare -A DEST=([forecast.py]=$PH/forecast.py [h25_live.py]=$W/arm2_live/h25_live.py [daily.py]=$W/experiments/pipeline/daily.py [input_guard.py]=$PH/input_guard.py)
rollback() { for f in forecast.py h25_live.py daily.py; do [ -f $BK/$f ] && cp $BK/$f ${DEST[$f]}.rb && mv ${DEST[$f]}.rb ${DEST[$f]}; done
  rm -f $PH/input_guard.py; [ -f $BK/arm3_live.py ] && cp $BK/arm3_live.py $W/arm3_live/arm3_live.py; for f in forecast.py h25_live.py daily.py; do echo "rollback $f -> $(m8 ${DEST[$f]})"; done; }
MODE=${1:-}; case "$MODE" in rollback|deploy) [ "$(id -un)" = agent ] || { echo "run as user agent"; exit 1; };; esac
case "$MODE" in rollback) rollback; exit 0;; check|deploy) ;; *) echo "usage: $0 check|deploy|rollback"; exit 64;; esac
if [ "$MODE" = deploy ]; then H=$(TZ=America/Los_Angeles date +%H%M); { [ "$H" -ge 0100 ] && [ "$H" -lt 2330 ]; } || { echo "inside 23:30-01:00 PT: not deploying"; exit 1; }; fi
[ "$(m8 $PH/features.py)" = 033d7bd7 ] || { echo "features.py is $(m8 $PH/features.py): deploy the today-rows fix first (live-code 1 passes the day explicitly)"; [ "$MODE" = deploy ] && exit 1; }
for f in "${!LIVE[@]}"; do [ "$(m8 $f)" = "${LIVE[$f]}" ] || { echo "$f is $(m8 $f), expected ${LIVE[$f]}: stop"; exit 1; }; done
for f in "${!NEW[@]}"; do [ "$(m8 $N/$f)" = "${NEW[$f]}" ] || { echo "staged $f is $(m8 $N/$f), expected ${NEW[$f]}: stop"; exit 1; }; done
[ -e $PH/input_guard.py ] && { echo "input_guard.py already present in ph_predict: stop"; exit 1; }
if [ "$MODE" = check ]; then bash $N/dry_livecode2.sh; exit $?; fi
mkdir -p $BK; for f in forecast.py h25_live.py daily.py; do cp -p ${DEST[$f]} $BK/$f; done
for f in forecast.py h25_live.py daily.py input_guard.py; do cp $N/$f ${DEST[$f]}.new && mv ${DEST[$f]}.new ${DEST[$f]}; done
ok=1; for f in forecast.py h25_live.py daily.py input_guard.py; do [ "$(m8 ${DEST[$f]})" = "${NEW[$f]}" ] || ok=0; done
(cd $PH && env -u PYTHONPATH $PY $N/import_gate.py $PH/forecast.py) || ok=0
(cd $PH && env PYTHONPATH=$W/arm2_live:. $PY $N/import_gate.py $W/arm2_live/h25_live.py) || ok=0
(cd $W/experiments && env -u PYTHONPATH $PY $N/import_gate.py -m:pipeline.daily) || ok=0
[ $ok = 1 ] || { echo "POST-INSTALL CHECK FAILED: rolling back"; rollback; exit 1; }
if [ -d $W/arm3_live ] && [ "$(m8 $N/arm3_live.py)" = e62eae24 ]; then cp -p $W/arm3_live/arm3_live.py $BK/arm3_live.py 2>/dev/null || true
  cp $N/arm3_live.py $W/arm3_live/arm3_live.py.new && mv $W/arm3_live/arm3_live.py.new $W/arm3_live/arm3_live.py; echo "arm3_live.py -> e62eae24"
else echo "arm3_live.py not installed (bundle 13 ~/w/arm3_live absent): arm 3 cannot be published until it is"; fi
echo "DEPLOYED live-code 2: forecast.py ${NEW[forecast.py]}, arm2_live/h25_live.py ${NEW[h25_live.py]}, pipeline/daily.py ${NEW[daily.py]}, input_guard.py ${NEW[input_guard.py]}; rollback: bash $N/deploy_livecode2.sh rollback"
