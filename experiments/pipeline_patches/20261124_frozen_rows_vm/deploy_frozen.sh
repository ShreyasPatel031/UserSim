#!/bin/bash
# Frozen forward shadows written from code on the VM (orchestrator 13:35Z Nov 24; timing only: no change to inputs, features or scoring).
# promo_posts and four_inputs rows were written by an agent-session scheduled task at 02:21 PT; with the session's worker down (Nov 24) the
# freeze time depended on a session. Now the VM's bundle-12a runner builds each row once from the 00:05 parquet and freezes it to
#   gs://usersim-bakeoff-347838016394/usersim_sim/results/frozen_rows/<line>/<d>.json   (never rewritten; on_time = written before 03:45 PT)
# and the session only copies bucket rows into the repo jsonl files (`pull`). A late row stays flagged late and unscored.
#   ~/w/tw12a/run.sh       8f032a1c -> 8c4805e7 (job case "frozen")
#   ~/w/tw12a/sched12a.txt 73c5b085 -> 6d2dcc76 ("01:25 frozen", retry "02:45 frozen"; both before the 03:45 PT cut)
#   ~/w/frozen_rows/ (new): promo_posts_shadow.py 38a0e7db, four_inputs_shadow.py f8375555, results/frozen/<the two frozen rule files>
# usage (VM, agent): bash deploy_frozen.sh check | rehearse <day> | selftest | deploy | rollback
set -u; W=/home/agent/w; N=$(cd "$(dirname "$0")" && pwd); TW=$W/tw12a; FR=/home/agent/w/frozen_rows; BK=$W/backup_tw12a; PY=/opt/exp/bin/python3
m8() { [ -e "$1" ] && md5sum < "$1" | cut -c1-8 || echo none; }
R_OLD=8f032a1c; R_NEW=8c4805e7; S_OLD=73c5b085; S_NEW=6d2dcc76; P1=38a0e7db; P2=f8375555
RULES="promo_posts_w01_20261120.json four_inputs_w01_20261123.json"
check() {   # $1 = tw dir, $2 = frozen_rows dir
  local ok=0
  [ "$(m8 $N/run.sh)" = $R_NEW ] || { echo "bundle run.sh $(m8 $N/run.sh) != $R_NEW"; ok=1; }
  [ "$(m8 $N/sched12a.txt)" = $S_NEW ] || { echo "bundle sched12a.txt != $S_NEW"; ok=1; }
  [ "$(m8 $N/promo_posts_shadow.py)" = $P1 ] || { echo "bundle promo_posts_shadow.py != $P1"; ok=1; }
  [ "$(m8 $N/four_inputs_shadow.py)" = $P2 ] || { echo "bundle four_inputs_shadow.py != $P2"; ok=1; }
  for r in $RULES; do [ -s $N/$r ] || { echo "bundle $r missing"; ok=1; }; done
  [ "$(m8 $1/run.sh)" = $R_OLD ] || { echo "installed run.sh $(m8 $1/run.sh) != $R_OLD"; ok=1; }
  [ "$(m8 $1/sched12a.txt)" = $S_OLD ] || { echo "installed sched12a.txt $(m8 $1/sched12a.txt) != $S_OLD"; ok=1; }
  [ -e $2 ] && { echo "$2 already exists"; ok=1; }
  bash -n $N/run.sh || { echo "run.sh syntax"; ok=1; }
  return $ok
}
install() {   # $1 = tw dir, $2 = frozen_rows dir, $3 = backup dir
  mkdir -p $3 && cp -p $1/run.sh $3/run.sh.$R_OLD && cp -p $1/sched12a.txt $3/sched12a.txt.$S_OLD || return 1
  mkdir -p $2/results/frozen && cp $N/promo_posts_shadow.py $N/four_inputs_shadow.py $2/ && for r in $RULES; do cp $N/$r $2/results/frozen/; done || return 1
  cp $N/run.sh $1/run.sh.new && mv $1/run.sh.new $1/run.sh && cp $N/sched12a.txt $1/sched12a.txt.new && mv $1/sched12a.txt.new $1/sched12a.txt
}
restore() { cp -p $3/run.sh.$R_OLD $1/run.sh && cp -p $3/sched12a.txt.$S_OLD $1/sched12a.txt && rm -rf "$2"; }
case "${1:-}" in
check) check $TW $FR && echo "CHECK OK";;
rehearse)   # the new job case end to end from scratch copies; uploads to gs:// are captured into scratch (never sent); log and status go to scratch
  D=${2:?day}; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; REAL=$(command -v gsutil); mkdir -p $T/bin $T/tw/logs $T/up
  printf '%s\n' '#!/bin/bash' 'last="${@: -1}"' \
    "for a in \"\$@\"; do case \"\$a\" in cp|rsync|mv) case \"\$last\" in gs://*) src=\"\${@: -2:1}\"; [ \"\$src\" = - ] && cat > /dev/null || cp \"\$src\" $T/up/\$(basename \$(dirname \"\$last\"))_\$(basename \"\$last\"); echo \"DRY gsutil: upload captured\" >&2; exit 0;; esac;; rm) echo \"DRY gsutil: rm refused\" >&2; exit 0;; esac; done" \
    "exec $REAL \"\$@\"" > $T/bin/gsutil; chmod +x $T/bin/gsutil
  mkdir -p $T/fr/results/frozen && cp $N/promo_posts_shadow.py $N/four_inputs_shadow.py $T/fr/ && for r in $RULES; do cp $N/$r $T/fr/results/frozen/; done
  sed -e "s#TW=/home/agent/w/tw12a#TW=$T/tw#" -e "s#/home/agent/w/tw12a.locks#$T/locks#g" -e "s#cd /home/agent/w/frozen_rows#cd $T/fr#" -e "s#D=\$(date +%F)#D=$D#" $N/run.sh > $T/run.sh
  grep -q "cd $T/fr" $T/run.sh || { echo "rehearsal sed failed"; exit 1; }
  PATH=$T/bin:$PATH bash $T/run.sh frozen; rc=$?
  tail -1 $T/tw/logs/$D.log | cut -c1-300
  ls $T/up | tr '\n' ' '; echo
  ok=1; for l in promo_posts four_inputs; do f=$T/up/${l}_$D.json
    [ -s $f ] && $PY -c "import json,hashlib; d=json.load(open('$f')); assert d['day']=='$D' and len(d['shadow_order'])==d['launches'] and 'on_time' in d; print('$l', d['launches'], 'launches, on_time', d['on_time'], 'top3_differs', d['top3_differs'], 'order md5', hashlib.md5(json.dumps(d['shadow_order']).encode()).hexdigest()[:8])" || ok=0; done
  [ $rc = 0 ] && [ $ok = 1 ] && echo "REHEARSAL PASSED" || { echo "REHEARSAL FAILED rc=$rc"; exit 1; };;
selftest)   # install + rollback against scratch copies of the installed tw12a files; md5s must round-trip and the new dir must go
  T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; mkdir -p $T/tw; cp -p $TW/run.sh $TW/sched12a.txt $T/tw/
  check $T/tw $T/fr >/dev/null || { echo "selftest: base mismatch"; exit 1; }
  install $T/tw $T/fr $T/bk || exit 1; a="$(m8 $T/tw/run.sh) $(m8 $T/tw/sched12a.txt) $(m8 $T/fr/promo_posts_shadow.py) $(m8 $T/fr/four_inputs_shadow.py)"
  restore $T/tw $T/fr $T/bk; b="$(m8 $T/tw/run.sh) $(m8 $T/tw/sched12a.txt) $([ -e $T/fr ] && echo present || echo gone)"
  [ "$a" = "$R_NEW $S_NEW $P1 $P2" ] && [ "$b" = "$R_OLD $S_OLD gone" ] && echo "SELFTEST OK: deploy -> $a; rollback -> $b" || { echo "SELFTEST FAILED: $a / $b"; exit 1; };;
deploy)
  H=$(TZ=America/Los_Angeles date +%H%M); { [ "$H" -ge 2330 ] || [ "$H" -lt 100 ]; } && { echo "refused: 23:30-01:00 PT"; exit 1; }
  check $TW $FR || { echo "refused: check failed"; exit 1; }
  install $TW $FR $BK || exit 1
  echo "DEPLOYED run.sh $(m8 $TW/run.sh), sched12a.txt $(m8 $TW/sched12a.txt), frozen_rows $(m8 $FR/promo_posts_shadow.py) $(m8 $FR/four_inputs_shadow.py); rollback: bash $N/deploy_frozen.sh rollback";;
rollback) restore $TW $FR $BK && echo "restored run.sh $(m8 $TW/run.sh), sched12a.txt $(m8 $TW/sched12a.txt); frozen_rows removed";;
*) echo "usage: check | rehearse <day> | selftest | deploy | rollback"; exit 64;;
esac
