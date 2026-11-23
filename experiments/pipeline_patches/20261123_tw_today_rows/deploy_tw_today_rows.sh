#!/bin/bash
# tw-tree TODAY-ROWS fix (orchestrator 22:42Z Nov 23: live hist_hunter_rel nulls). The tw tree (~/w/tw/experiments/ph_predict, cwd of every tw
# job) still runs features.py 981c5ded, which reads EVERY data/today/*.json file: stale unlabelled rows enter add_history and leave
# hist_hunter_rel NaN for hunters with history. The deployed pipeline has had the fix since Nov 15 (033d7bd7); the tw copy never got it.
# arm2_shap.py (tw, 01:05 PT) refits arm 2 with that copy and its h25_live call re-uploaded raw/daily/<d>/arm2_input_nulls_<d>.json,
# overwriting the 00:05 forecast's own (clean) sidecar: that is the 7-58% the audit read.
#   (a) ~/w/tw/experiments/ph_predict/features.py  981c5ded -> 033d7bd7 (= the deployed pipeline copy; diff = the TODAY-ROWS fix only)
#   (b) ~/w/tw/experiments/ph_predict/arm2_shap.py 71dbc3c5 -> 91f2fb15 (its refit's null sidecar goes to a local file, never the bucket)
# usage (VM, agent): bash deploy_tw_today_rows.sh check | rehearse <day> | selftest | deploy | rollback
set -u; W=/home/agent/w; N=$(cd "$(dirname "$0")" && pwd); P=$W/tw/experiments/ph_predict; BK=$W/backup_tw_today_rows; PY=/opt/exp/bin/python3
m8() { [ -e "$1" ] && md5sum < "$1" | cut -c1-8 || echo none; }
F_OLD=981c5ded; F_NEW=033d7bd7; S_OLD=71dbc3c5; S_NEW=91f2fb15
check() {   # $1 = target dir
  local t=$1 ok=0
  [ "$(m8 $N/features.py)" = $F_NEW ] || { echo "bundle features.py $(m8 $N/features.py) != $F_NEW"; ok=1; }
  [ "$(m8 $N/arm2_shap.py)" = $S_NEW ] || { echo "bundle arm2_shap.py $(m8 $N/arm2_shap.py) != $S_NEW"; ok=1; }
  [ "$(m8 $W/experiments/ph_predict/features.py)" = $F_NEW ] || { echo "deployed pipeline features.py is not $F_NEW"; ok=1; }
  [ "$(m8 $t/features.py)" = $F_OLD ] || { echo "installed tw features.py $(m8 $t/features.py) != $F_OLD"; ok=1; }
  [ "$(m8 $t/arm2_shap.py)" = $S_OLD ] || { echo "installed tw arm2_shap.py $(m8 $t/arm2_shap.py) != $S_OLD"; ok=1; }
  return $ok
}
install() {   # $1 = target dir, $2 = backup dir
  local t=$1 b=$2; mkdir -p $b && cp -p $t/features.py $b/features.py.$F_OLD && cp -p $t/arm2_shap.py $b/arm2_shap.py.$S_OLD || return 1
  cp $N/features.py $t/features.py.new && mv $t/features.py.new $t/features.py && cp $N/arm2_shap.py $t/arm2_shap.py.new && mv $t/arm2_shap.py.new $t/arm2_shap.py
  (cd $t && $PY -c "import ast; [ast.parse(open(f).read()) for f in ('features.py', 'arm2_shap.py')]") || { restore $t $b; echo "parse failed: rolled back"; return 1; }
}
restore() { cp -p $2/features.py.$F_OLD $1/features.py && cp -p $2/arm2_shap.py.$S_OLD $1/arm2_shap.py; }
case "${1:-}" in
check) check $P && echo "CHECK OK: installed tw files are the expected base; bundle files match";;
rehearse)   # end to end, DRY: scratch copy of the tw code, real data read-only, gsutil stub refuses uploads/rm, sidecars captured to scratch
  D=${2:?day}; H=$(TZ=America/Los_Angeles date +%H%M); [ "$H" -ge 0005 ] && [ "$H" -lt 0100 ] && { echo "refused: 00:05-01:00 PT"; exit 1; }
  T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; REAL=$(command -v gsutil); mkdir -p $T/bin
  printf '%s\n' '#!/bin/bash' 'last="${@: -1}"' 'for a in "$@"; do case "$a" in cp|rsync|mv) case "$last" in gs://*) echo "DRY gsutil: upload refused" >&2; exit 0;; esac;; rm) echo "DRY gsutil: rm refused" >&2; exit 0;; esac; done' "exec $REAL \"\$@\"" > $T/bin/gsutil; chmod +x $T/bin/gsutil
  for v in old new; do
    mkdir -p $T/$v/results; (cd $P && find . -maxdepth 1 -name '*.py' -exec cp {} $T/$v/ \;); ln -s $(realpath $P/data) $T/$v/data
    [ $v = new ] && { cp $N/features.py $T/$v/features.py; cp $N/arm2_shap.py $T/$v/arm2_shap.py; }
    cat > $T/$v/wrap.py <<PYEOF
import os, sys, json, runpy
os.chdir("$T/$v"); sys.path.insert(0, "$T/$v"); sys.path.insert(0, "$W/arm2_live")   # as arm2_shap does: the pinned arm2_live h25_live wins over the tw copy
import h25_live; assert h25_live.__file__.startswith("$W/arm2_live"), h25_live.__file__
def cap(day, te, cc, real):
    json.dump({"rel_null_given_history": round(float((te.hist_hunter_rel.isna() & (te.hist_hunter_n > 0)).sum()) / max(1, int((te.hist_hunter_n > 0).sum())), 4),
               "with_history": int((te.hist_hunter_n > 0).sum()), "rows": len(te)}, open("$T/$v/cap.json", "w"))
h25_live._write_input_nulls = cap
sys.argv = ["arm2_shap.py", "$D"]; runpy.run_path("arm2_shap.py", run_name="__main__")
PYEOF
    out=$(cd $T/$v && PATH=$T/bin:/opt/exp/bin:$PATH DRY=1 nice -n 10 $PY wrap.py 2>&1); rc=$?
    nul=$( [ $v = new ] && cat $T/$v/results/shadow_arm2_shap/${D}_input_nulls.json 2>/dev/null | $PY -c "import sys,json; print(json.load(sys.stdin)['null_rate'].get('hist_hunter_rel|has_history'))" || cat $T/$v/cap.json 2>/dev/null)
    chk=$(cat $T/$v/results/shadow_arm2_shap/$D.json 2>/dev/null | $PY -c "import sys,json; print(json.load(sys.stdin).get('checks'))" 2>/dev/null)
    echo "$v rc=$rc | hunter-rel null (share of launches with history / of all rows for new): $nul | $chk"
    [ $rc = 0 ] || { echo "$out" | tail -5; exit 1; }
  done; echo "REHEARSAL PASSED";;
selftest)   # deploy + rollback against a scratch copy of the tw files; md5s must round-trip
  T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; cp -p $P/features.py $P/arm2_shap.py $T/
  check $T >/dev/null || { echo "selftest: base mismatch"; exit 1; }
  install $T $T/bk || exit 1; a="$(m8 $T/features.py) $(m8 $T/arm2_shap.py)"
  restore $T $T/bk; b="$(m8 $T/features.py) $(m8 $T/arm2_shap.py)"
  [ "$a" = "$F_NEW $S_NEW" ] && [ "$b" = "$F_OLD $S_OLD" ] && echo "SELFTEST OK: deploy -> $a; rollback -> $b" || { echo "SELFTEST FAILED: $a / $b"; exit 1; };;
deploy)
  H=$(TZ=America/Los_Angeles date +%H%M); { [ "$H" -ge 2330 ] || [ "$H" -lt 100 ]; } && { echo "refused: 23:30-01:00 PT"; exit 1; }
  check $P || { echo "refused: check failed"; exit 1; }
  install $P $BK || exit 1
  echo "DEPLOYED tw features.py $(m8 $P/features.py), arm2_shap.py $(m8 $P/arm2_shap.py); rollback: bash $N/deploy_tw_today_rows.sh rollback";;
rollback) restore $P $BK && echo "restored tw features.py $(m8 $P/features.py), arm2_shap.py $(m8 $P/arm2_shap.py)";;
*) echo "usage: check | rehearse <day> | selftest | deploy | rollback"; exit 64;;
esac
