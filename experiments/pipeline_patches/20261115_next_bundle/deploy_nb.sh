#!/bin/bash
# Next bundle (NOT DEPLOYED; deploys only on Shreyas's word). usage: bash deploy_nb.sh check|deploy|rollback
#   ctrl.py           -> ~/w/arm2_live/ctrl.py (tracked copy of the hand-added file; md5 b47fc28f)
#   readable_shadow.py -> ~/w/tw/h25/readable_shadow.py (adds per-launch "values" = raw X10 inputs; needs bundle 12.8 deployed)
set -u; W=/home/agent/w; N=$(cd "$(dirname "$0")" && pwd); M="${1:?check|deploy|rollback}"; BK=$W/nb_backup
[ "$(id -un)" = agent ] || { echo "run as agent"; exit 1; }
H=$(TZ=America/Los_Angeles date +%H%M); if [ "$M" != check ] && { [ "$H" -ge 2330 ] || [ "$H" -lt 100 ]; }; then echo "refused: 23:30-01:00 PT"; exit 1; fi
(cd $N && md5sum -c --quiet MANIFEST.md5) || { echo "manifest mismatch"; exit 1; }
gate() { echo "gate: $1"; (eval "$2") || { echo "import gate failed: $1"; exit 1; }; }
G="cd $W/experiments/ph_predict && env PYTHONPATH"
if [ "$M" = check ]; then
  T=$(mktemp -d); mkdir -p $T/arm2_live $T/h25; cp $W/arm2_live/*.py $T/arm2_live/; cp $N/ctrl.py $T/arm2_live/; cp $N/readable_shadow.py $T/h25/
  gate "h25_live with bundle ctrl.py" "$G=$T/arm2_live:. /opt/exp/bin/python3 $N/import_gate.py $T/arm2_live/h25_live.py"
  gate "readable_shadow (tw.sh PYTHONPATH)" "$G=$W/mk:. /opt/exp/bin/python3 $N/import_gate.py $T/h25/readable_shadow.py"
  grep -q '"values"' $T/h25/readable_shadow.py && echo "values field present"; rm -rf "$T"; echo "check passed"; exit 0
fi
if [ "$M" = deploy ]; then
  [ -d $W/tw/h25 ] || { echo "refused: bundle 12.8 (~/w/tw) not deployed"; exit 1; }
  mkdir -p $BK; cp -p $W/arm2_live/ctrl.py $BK/ctrl.py 2>/dev/null; cp -p $W/tw/h25/readable_shadow.py $BK/readable_shadow.py
  cp $N/ctrl.py $W/arm2_live/ctrl.py.new && mv $W/arm2_live/ctrl.py.new $W/arm2_live/ctrl.py
  cp $N/readable_shadow.py $W/tw/h25/readable_shadow.py.new && mv $W/tw/h25/readable_shadow.py.new $W/tw/h25/readable_shadow.py
  ok=1
  (eval "$G=$W/arm2_live:. /opt/exp/bin/python3 $N/import_gate.py $W/arm2_live/h25_live.py") || ok=0
  (eval "$G=$W/mk:. /opt/exp/bin/python3 $N/import_gate.py $W/tw/h25/readable_shadow.py") || ok=0
  [ $ok = 1 ] || { echo "import gate failed after install: rolling back"; bash $N/deploy_nb.sh rollback; exit 1; }
  echo "DEPLOYED next bundle; rollback: bash $N/deploy_nb.sh rollback"; exit 0
fi
if [ "$M" = rollback ]; then
  [ -f $BK/readable_shadow.py ] && cp -p $BK/readable_shadow.py $W/tw/h25/readable_shadow.py
  [ -f $BK/ctrl.py ] && cp -p $BK/ctrl.py $W/arm2_live/ctrl.py
  echo "rolled back"; exit 0
fi
echo "unknown mode"; exit 1
