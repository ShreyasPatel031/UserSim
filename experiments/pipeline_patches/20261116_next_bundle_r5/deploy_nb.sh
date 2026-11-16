#!/bin/bash
# Next bundle r5 (r4 + end-to-end rehearsal: rehearse.sh, run by run_chain.sh between check and deploy). Deploy through run_chain.sh, which stops on a failed check.  usage: bash deploy_nb.sh check|deploy_h25|deploy|rollback
#   deploy_h25  arm 2 only (no bundle 12.8 needed): rootlink.py + h25_live (llm-link / shared root builder) into ~/w/arm2_live
#   deploy      everything; needs bundle 12.8 (~/w/tw):
#     ~/w/arm2_live: rootlink.py, h25_live.py (variant picked by the installed md5), ctrl.py (tracked copy, b47fc28f)
#     ~/w/tw/h25: readable_shadow.py (raw "values"; ph_n_makers == 0 -> missing), h25_shadow.py + history_retrain.py (shared root builder), rootlink.py
#     ~/w/tw/experiments/ph_predict: arm2_shap.py (arm 2 TreeSHAP + per-input + raw values), comment_forecast.py (refresh cached copies), rootlink.py
#     ~/w/tw/tw.sh: sync_wh failures logged + alert file
#     ~/w/arm3_live: arm3_live.py (shared root builder) + rootlink.py, only if live-code 2's arm3_live (e62eae24) is installed
#   Every replaced file must have its expected base md5, or nothing is changed. Backups in ~/w/nb_backup; rollback restores them.
set -u; W=${NB_W:-/home/agent/w}; N=$(cd "$(dirname "$0")" && pwd); M="${1:?check|deploy_h25|deploy|rollback}"; BK=$W/nb_backup; PY=/opt/exp/bin/python3
[ "$(id -un)" = agent ] || { echo "run as agent"; exit 1; }
H=$(TZ=America/Los_Angeles date +%H%M); if [ "$M" != check ] && [ "$M" != rollback ] && { [ "$H" -ge 2330 ] || [ "$H" -lt 100 ]; }; then echo "refused: 23:30-01:00 PT"; exit 1; fi
(cd $N && md5sum -c --quiet MANIFEST.md5) || { echo "manifest mismatch"; exit 1; }
m8() { [ -e "$1" ] && md5sum < "$1" | cut -c1-8 || echo none; }
h25src() { case $(m8 $1) in ff40d796|88c206ce|2f49972b) echo h25_live.py;; e3af37b4|66a1a4b1|364b3b2a) echo h25_live_cur.py;; *) echo "";; esac; }
# plan lines: <src> <dest> <allowed base md5s, comma; "new" = may be absent; "any" = no check>
plan() {   # $1 = root prefix (W for deploy, scratch mirror for check); $2 = h25 | all
  local R=$1; local s; s=$(h25src $R/arm2_live/h25_live.py)
  [ -n "$s" ] || { echo "PLANFAIL arm2_live/h25_live.py md5 $(m8 $R/arm2_live/h25_live.py) not ff40d796/e3af37b4"; return; }
  echo "rootlink.py $R/arm2_live/rootlink.py new,38e37fba"
  echo "$s $R/arm2_live/h25_live.py ff40d796,e3af37b4,88c206ce,66a1a4b1,2f49972b,364b3b2a"
  [ "$2" = h25 ] && return
  echo "ctrl.py $R/arm2_live/ctrl.py any"
  echo "readable_shadow.py $R/tw/h25/readable_shadow.py c26c69be,2851a666,75717237"
  echo "h25_shadow.py $R/tw/h25/h25_shadow.py 7d9ec545,d215f867"
  echo "history_retrain.py $R/tw/h25/history_retrain.py a3f9de9b,4f3dbc1c"
  echo "rootlink.py $R/tw/h25/rootlink.py new,38e37fba"
  echo "arm2_shap.py $R/tw/experiments/ph_predict/arm2_shap.py bd0ae425,92f9e80d,71dbc3c5"
  echo "comment_forecast.py $R/tw/experiments/ph_predict/comment_forecast.py ef9264a1,b17ce67a"
  echo "rootlink.py $R/tw/experiments/ph_predict/rootlink.py new,38e37fba"
  echo "tw.sh $R/tw/tw.sh 422f1396,e1e6c8c1"
  if [ "$(m8 $R/arm3_live/arm3_live.py)" = e62eae24 ] || [ "$(m8 $R/arm3_live/arm3_live.py)" = 52ba59d5 ]; then
    echo "arm3_live.py $R/arm3_live/arm3_live.py e62eae24,52ba59d5"; echo "rootlink.py $R/arm3_live/rootlink.py new,38e37fba"
  else echo "NOTE arm3_live not at live-code 2 (e62eae24): arm3 overlay skipped" >&2; fi
}
verify() { local bad=0; while read -r src dst ok; do
    [ "$src" = PLANFAIL ] && { echo "refused: $dst $ok"; bad=1; continue; }
    [ "$ok" = any ] && continue; cur=$(m8 $dst)
    if [ "$cur" = none ]; then case ",$ok," in *,new,*) ;; *) echo "refused: $dst missing"; bad=1;; esac
    else case ",$ok," in *",$cur,"*) ;; *) echo "refused: $dst md5 $cur not in {$ok}"; bad=1;; esac; fi
  done; return $bad; }
install() { mkdir -p $BK; touch $BK/map.txt $BK/created.txt; while read -r src dst ok; do
    if [ -e "$dst" ]; then grep -qF "	$dst" $BK/map.txt || { b=$BK/f$(wc -l < $BK/map.txt); cp -p "$dst" "$b"; printf '%s\t%s\n' "$b" "$dst" >> $BK/map.txt; }
    else grep -qxF "$dst" $BK/created.txt || echo "$dst" >> $BK/created.txt; fi
    cp "$N/$src" "$dst.new" && mv "$dst.new" "$dst"; done; }
gates() { local R=$1 ok=1; local G="env PYTHONPATH"
  (cd $W/experiments/ph_predict && $G=$R/arm2_live:. $PY $N/import_gate.py $R/arm2_live/h25_live.py) || ok=0
  if [ "$2" = all ]; then
    (cd $W/experiments/ph_predict && $G=$W/mk:. $PY $N/import_gate.py $R/tw/h25/readable_shadow.py) || ok=0
    (cd $W/experiments/ph_predict && $G=$W/mk:.:$R/tw/h25 $PY $N/import_gate.py $R/tw/h25/h25_shadow.py) || ok=0
    (cd $R/tw/experiments/ph_predict && $G=. $PY $N/import_gate.py arm2_shap.py comment_forecast.py) || ok=0
    bash -n $R/tw/tw.sh || ok=0
    [ -f $R/arm3_live/rootlink.py ] && { (cd $W/experiments/ph_predict && $G=$R/arm3_live:$R/arm2_live:. $PY $N/import_gate.py $R/arm3_live/arm3_live.py) || ok=0; }
  fi
  [ $ok = 1 ]; }
if [ "$M" = check ]; then
  T=$(mktemp -d); mkdir -p $T/arm2_live $T/arm3_live $T/tw/h25 $T/tw/experiments/ph_predict; MODE=all
  cp $W/arm2_live/*.py $T/arm2_live/
  if [ -f $W/arm3_live/arm3_live.py ]; then cp $W/arm3_live/*.py $T/arm3_live/; else cp $W/stage/arm3/*.py $T/arm3_live/ 2>/dev/null; cp $N/base_12_8/arm3_live.py $T/arm3_live/; fi
  if [ -d $W/tw ]; then cp $W/tw/h25/*.py $T/tw/h25/; cp $W/tw/experiments/ph_predict/*.py $T/tw/experiments/ph_predict/; cp -r $W/tw/experiments/pipeline $T/tw/experiments/; cp $W/tw/tw.sh $T/tw/; SRC="installed 12.8"   # r2: the pipeline package too (Nov 16 check-mode false FAIL)
  else  # 12.8 not deployed: the check mirror is 12.8's own code tarball (deploy/b12/tw_code_a6626fcf.tgz, md5 ee976fde)
    gsutil -q cp gs://usersim-bakeoff-347838016394/usersim_sim/deploy/b12/tw_code_a6626fcf.tgz $T/tw.tgz || { echo "check FAILED: 12.8 tarball unreadable"; exit 1; }
    [ "$(m8 $T/tw.tgz)" = ee976fde ] || { echo "check FAILED: 12.8 tarball md5 $(m8 $T/tw.tgz) != ee976fde"; exit 1; }
    rm -rf $T/tw; tar xzf $T/tw.tgz -C $T; SRC="12.8 code tarball ee976fde (12.8 not deployed)"; fi
  echo "check mirror: $SRC"
  PL=$(plan $T $MODE); echo "$PL" | verify || { echo "check FAILED (base md5)"; rm -rf "$T"; exit 1; }
  echo "$PL" | while read -r src dst ok; do cp "$N/$src" "$dst"; done
  gates $T $MODE && echo "gates ok ($MODE)" || { echo "check FAILED (gates)"; rm -rf "$T"; exit 1; }
  grep -q '"values"' $T/tw/experiments/ph_predict/arm2_shap.py 2>/dev/null && echo "arm2_shap values present"
  rm -rf "$T"; echo "check passed ($MODE)"; exit 0
fi
if [ "$M" = deploy_h25 ] || [ "$M" = deploy ]; then
  MODE=h25; [ "$M" = deploy ] && { [ -d $W/tw/h25 ] || { echo "refused: bundle 12.8 (~/w/tw) not deployed; use deploy_h25 for the arm-2 fix alone"; exit 1; }; MODE=all; }
  PL=$(plan $W $MODE); echo "$PL" | verify || exit 1
  echo "$PL" | install
  gates $W $MODE || { echo "import gate failed after install: rolling back"; bash $N/deploy_nb.sh rollback; exit 1; }
  echo "DEPLOYED next bundle ($M); rollback: bash $N/deploy_nb.sh rollback"; exit 0
fi
if [ "$M" = rollback ]; then
  [ -d $BK ] || { echo "nothing to roll back"; exit 0; }
  [ -f $BK/map.txt ] && while IFS=$'\t' read -r b dst; do cp -p "$b" "$dst" && echo "restored $dst"; done < $BK/map.txt
  [ -f $BK/created.txt ] && while read -r f; do [ -n "$f" ] && rm -f -- "$f" && echo "removed $f"; done < $BK/created.txt
  mv $BK $BK.rolled_back_$(date -u +%Y%m%dT%H%MZ); echo "rolled back"; exit 0
fi
echo "unknown mode"; exit 1
