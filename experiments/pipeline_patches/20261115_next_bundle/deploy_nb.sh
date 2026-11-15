#!/bin/bash
# Next bundle (NOT DEPLOYED; deploys only on Shreyas's word). usage: bash deploy_nb.sh check|deploy|deploy_h25|rollback
#   ctrl.py           -> ~/w/arm2_live/ctrl.py (tracked copy of the hand-added file; md5 b47fc28f)
#   readable_shadow.py -> ~/w/tw/h25/readable_shadow.py (adds per-launch "values" = raw X10 inputs; ph_n_makers == 0 -> missing; needs 12.8)
#   h25_live.py / h25_live_cur.py -> ~/w/arm2_live/h25_live.py: links each new llm_*_gemini file into arm 2's private data root (llm_pitch and
#                        llm_brand were null for every launch from Nov 14). h25_live.py = live-code 2's ff40d796 + fix; h25_live_cur.py =
#                        the currently deployed e3af37b4 + fix; the installed md5 picks one. Mode deploy_h25 installs only this fix (no 12.8 needed).
#   arm2_shap.py      -> ~/w/tw/experiments/ph_predict/arm2_shap.py (12.8's why_drivers job already runs it nightly after the 00:05
#                        forecast; this version adds arm 2's raw input values per launch)
set -u; W=/home/agent/w; N=$(cd "$(dirname "$0")" && pwd); M="${1:?check|deploy|deploy_h25|rollback}"; BK=$W/nb_backup
[ "$(id -un)" = agent ] || { echo "run as agent"; exit 1; }
H=$(TZ=America/Los_Angeles date +%H%M); if [ "$M" != check ] && { [ "$H" -ge 2330 ] || [ "$H" -lt 100 ]; }; then echo "refused: 23:30-01:00 PT"; exit 1; fi
(cd $N && md5sum -c --quiet MANIFEST.md5) || { echo "manifest mismatch"; exit 1; }
gate() { echo "gate: $1"; (eval "$2") || { echo "import gate failed: $1"; exit 1; }; }
G="cd $W/experiments/ph_predict && env PYTHONPATH"
if [ "$M" = check ]; then
  T=$(mktemp -d); mkdir -p $T/arm2_live $T/h25 $T/ph; cp $W/arm2_live/*.py $T/arm2_live/; cp $N/ctrl.py $T/arm2_live/; cp $N/readable_shadow.py $T/h25/; cp $N/arm2_shap.py $T/ph/
  gate "h25_live with bundle ctrl.py" "$G=$T/arm2_live:. /opt/exp/bin/python3 $N/import_gate.py $T/arm2_live/h25_live.py"
  gate "readable_shadow (tw.sh PYTHONPATH)" "$G=$W/mk:. /opt/exp/bin/python3 $N/import_gate.py $T/h25/readable_shadow.py"
  for v in h25_live.py h25_live_cur.py; do T2=$(mktemp -d); cp $W/arm2_live/*.py $T2/; cp $N/ctrl.py $T2/; cp $N/$v $T2/h25_live.py
    gate "llm-link fix $v" "$G=$T2:. /opt/exp/bin/python3 $N/import_gate.py $T2/h25_live.py"; rm -rf "$T2"; done
  gate "arm2_shap (tw.sh nicep: cwd ph_predict)" "$G=. /opt/exp/bin/python3 $N/import_gate.py $T/ph/arm2_shap.py"
  grep -q '"values"' $T/h25/readable_shadow.py && grep -q '"values"' $T/ph/arm2_shap.py && echo "values field present (readable_shadow, arm2_shap)"; rm -rf "$T"; echo "check passed"; exit 0
fi
h25fix() {
  cur=$(md5sum < $W/arm2_live/h25_live.py | cut -c1-8)
  case $cur in ff40d796) src=h25_live.py;; e3af37b4) src=h25_live_cur.py;; *) echo "refused: arm2_live/h25_live.py is $cur (expected ff40d796 or e3af37b4)"; exit 1;; esac
  mkdir -p $BK; cp -p $W/arm2_live/h25_live.py $BK/h25_live.py
  cp $N/$src $W/arm2_live/h25_live.py.new && mv $W/arm2_live/h25_live.py.new $W/arm2_live/h25_live.py
  (cd $W/experiments/ph_predict && env PYTHONPATH=$W/arm2_live:. /opt/exp/bin/python3 $N/import_gate.py $W/arm2_live/h25_live.py) || { cp -p $BK/h25_live.py $W/arm2_live/h25_live.py; echo "gate failed: h25_live restored"; exit 1; }
  echo "llm-link fix installed ($src over $cur)"
}
if [ "$M" = deploy_h25 ]; then h25fix; echo "rollback: bash $N/deploy_nb.sh rollback"; exit 0; fi
if [ "$M" = deploy ]; then
  [ -d $W/tw/h25 ] || { echo "refused: bundle 12.8 (~/w/tw) not deployed"; exit 1; }
  mkdir -p $BK; cp -p $W/arm2_live/ctrl.py $BK/ctrl.py 2>/dev/null; cp -p $W/tw/h25/readable_shadow.py $BK/readable_shadow.py
  cp -p $W/tw/experiments/ph_predict/arm2_shap.py $BK/arm2_shap.py 2>/dev/null
  cp $N/ctrl.py $W/arm2_live/ctrl.py.new && mv $W/arm2_live/ctrl.py.new $W/arm2_live/ctrl.py
  cp $N/readable_shadow.py $W/tw/h25/readable_shadow.py.new && mv $W/tw/h25/readable_shadow.py.new $W/tw/h25/readable_shadow.py
  cp $N/arm2_shap.py $W/tw/experiments/ph_predict/arm2_shap.py.new && mv $W/tw/experiments/ph_predict/arm2_shap.py.new $W/tw/experiments/ph_predict/arm2_shap.py
  ok=1
  (eval "$G=$W/arm2_live:. /opt/exp/bin/python3 $N/import_gate.py $W/arm2_live/h25_live.py") || ok=0
  (eval "$G=$W/mk:. /opt/exp/bin/python3 $N/import_gate.py $W/tw/h25/readable_shadow.py") || ok=0
  (cd $W/tw/experiments/ph_predict && env PYTHONPATH=. /opt/exp/bin/python3 $N/import_gate.py arm2_shap.py) || ok=0
  [ $ok = 1 ] || { echo "import gate failed after install: rolling back"; bash $N/deploy_nb.sh rollback; exit 1; }
  h25fix
  echo "DEPLOYED next bundle; rollback: bash $N/deploy_nb.sh rollback"; exit 0
fi
if [ "$M" = rollback ]; then
  [ -f $BK/readable_shadow.py ] && cp -p $BK/readable_shadow.py $W/tw/h25/readable_shadow.py
  [ -f $BK/ctrl.py ] && cp -p $BK/ctrl.py $W/arm2_live/ctrl.py
  [ -f $BK/h25_live.py ] && cp -p $BK/h25_live.py $W/arm2_live/h25_live.py
  [ -f $BK/arm2_shap.py ] && cp -p $BK/arm2_shap.py $W/tw/experiments/ph_predict/arm2_shap.py
  echo "rolled back"; exit 0
fi
echo "unknown mode"; exit 1
