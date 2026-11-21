#!/bin/bash
# early_shock drop-out fix (popscore e5240e4a): launches dropped from the featured list no longer block a day. No writes or network added.
# usage (VM, agent): bash deploy_early_shock.sh rehearse | deploy | rollback.  Base 240ddc43 required.
set -u; W=/home/agent/w; N=$(cd "$(dirname "$0")" && pwd); PH=$W/experiments/ph_predict; DST=$PH/early_shock.py; BK=$W/backup_early_shock; PY=/opt/exp/bin/python3
m8() { md5sum < "$1" | cut -c1-8; }
case "${1:-}" in
rehearse)   # end to end, DRY: scratch copy of ph_predict code, real data read-only, scratch results, --force (all arms on the clean days), no --write
  T=$(mktemp -d); mkdir -p $T/ph; cp $PH/*.py $T/ph/; cp $N/early_shock.py $T/ph/early_shock.py; ln -s $(realpath $PH/data) $T/ph/data; mkdir -p $T/ph/results
  for x in sim_live; do [ -e $PH/results/$x ] && ln -s $(realpath $PH/results/$x) $T/ph/results/$x; done; cp $PH/results/forecast_*.parquet $T/ph/results/ 2>/dev/null
  cp -r $W/experiments/pipeline $T/pipeline
  out=$(cd $T/ph && PYTHONPATH=$T timeout 1500 $PY early_shock.py --force 2>&1); rc=$?
  echo "$out" | grep '"early_shock"' | cut -c1-300; echo "$out" | grep -iE "comment|H[0-9]|n/a" | head -12 | cut -c1-200
  rm -rf "$T"
  [ $rc = 0 ] && { echo "REHEARSAL PASSED"; exit 0; } || { echo "REHEARSAL FAILED rc=$rc"; echo "$out" | tail -5 | cut -c1-200; exit 1; };;
deploy)
  H=$(TZ=America/Los_Angeles date +%H%M); { [ "$H" -ge 2330 ] || [ "$H" -lt 100 ]; } && { echo "refused: 23:30-01:00 PT"; exit 1; }
  [ "$(m8 $DST)" = 240ddc43 ] || { echo "refused: installed early_shock.py $(m8 $DST) != 240ddc43"; exit 1; }
  mkdir -p $BK && cp -p $DST $BK/early_shock.py.240ddc43 && cp $N/early_shock.py $DST.new && mv $DST.new $DST
  (cd $PH && $PY -c "import ast; ast.parse(open('early_shock.py').read())") || { cp -p $BK/early_shock.py.240ddc43 $DST; echo "parse failed: rolled back"; exit 1; }
  echo "DEPLOYED early_shock.py $(m8 $DST); rollback: bash $N/deploy_early_shock.sh rollback";;
rollback) cp -p $BK/early_shock.py.240ddc43 $DST && echo "restored $(m8 $DST)";;
*) echo "usage: rehearse|deploy|rollback"; exit 64;;
esac
