#!/bin/bash
# Website forecast copy written once (orchestrator 03:48Z Nov 26): heartbeat showed forecast_0005 "late 236 min" on Nov 25. Cause: tw.sh runs
# web_forecast_0005.py after every pre-reveal point (and its 01:10 / catch-up slots); the script rewrote today's file on every run and re-stamped
# the heartbeat, so the last rewrite (P4, 12:01Z) became the recorded write time. The first real write was 09:01Z (56 min after the cut).
# Fix (timing only, same content): an unchanged file is neither rewritten, re-uploaded nor re-beaten.
#   ~/w/tw/experiments/ph_predict/web_forecast_0005.py 7645b1eb -> 0293f025
# usage (VM, agent): bash deploy_wf.sh check | rehearse <day> | selftest | deploy | rollback
set -u; W=/home/agent/w; N=$(cd "$(dirname "$0")" && pwd); P=$W/tw/experiments/ph_predict; BK=$W/backup_web_forecast_once; PY=/opt/exp/bin/python3
m8() { [ -e "$1" ] && md5sum < "$1" | cut -c1-8 || echo none; }
OLD=7645b1eb; NEW=0293f025
check() { local ok=0
  [ "$(m8 $N/web_forecast_0005.py)" = $NEW ] || { echo "bundle file != $NEW"; ok=1; }
  [ "$(m8 $1/web_forecast_0005.py)" = $OLD ] || { echo "installed $(m8 $1/web_forecast_0005.py) != $OLD"; ok=1; }
  $PY -c "import ast; ast.parse(open('$N/web_forecast_0005.py').read())" || ok=1; return $ok; }
install() { mkdir -p $2 && cp -p $1/web_forecast_0005.py $2/web_forecast_0005.py.$OLD && cp $N/web_forecast_0005.py $1/web_forecast_0005.py.new && mv $1/web_forecast_0005.py.new $1/web_forecast_0005.py; }
restore() { cp -p $2/web_forecast_0005.py.$OLD $1/web_forecast_0005.py; }
case "${1:-}" in
check) check $P && echo "CHECK OK";;
rehearse)   # new script from a scratch copy, real warehouse read-only, uploads captured: (a) seeded with today's real file -> must skip, no upload;
            # (b) without it -> must write and upload the same forecast
  D=${2:?day}; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; REAL=$(command -v gsutil); mkdir -p $T/bin $T/up $T/exp/ph_predict/results/web/forecast_0005
  printf '%s\n' '#!/bin/bash' 'last="${@: -1}"' "for a in \"\$@\"; do case \"\$a\" in cp|rsync|mv) case \"\$last\" in gs://*) cp \"\${@: -2:1}\" $T/up/ 2>/dev/null; echo DRY >&2; exit 0;; esac;; esac; done" "exec $REAL \"\$@\"" > $T/bin/gsutil; chmod +x $T/bin/gsutil
  cp $N/web_forecast_0005.py $P/heartbeat.py $T/exp/ph_predict/; ln -s $(realpath $P/../pipeline) $T/exp/pipeline
  cp $P/results/web/forecast_0005/$D.json $T/exp/ph_predict/results/web/forecast_0005/
  a=$(cd $T/exp/ph_predict && PATH=$T/bin:/opt/exp/bin:$PATH $PY web_forecast_0005.py $D 2>&1 | tail -1); na=$(ls $T/up | wc -l)
  rm $T/exp/ph_predict/results/web/forecast_0005/$D.json
  b=$(cd $T/exp/ph_predict && PATH=$T/bin:/opt/exp/bin:$PATH $PY web_forecast_0005.py $D 2>&1 | tail -1); nb=$(ls $T/up | wc -l)
  same=$($PY -c "import json; a=json.load(open('$P/results/web/forecast_0005/$D.json')); b=json.load(open('$T/exp/ph_predict/results/web/forecast_0005/$D.json')); print(a['forecast']==b['forecast'] and a['run_updated_at']==b['run_updated_at'])")
  echo "seeded: $a | uploads $na"; echo "fresh: $b | uploads $nb | same forecast as installed file: $same"
  echo "$a" | grep -q "unchanged" && [ $na = 0 ] && [ $nb -ge 1 ] && [ "$same" = True ] && echo "REHEARSAL PASSED" || { echo "REHEARSAL FAILED"; exit 1; };;
selftest) T=$(mktemp -d); trap 'rm -rf "$T"' EXIT; cp -p $P/web_forecast_0005.py $T/; check $T >/dev/null || { echo "base mismatch"; exit 1; }
  install $T $T/bk; a=$(m8 $T/web_forecast_0005.py); restore $T $T/bk; b=$(m8 $T/web_forecast_0005.py)
  [ "$a $b" = "$NEW $OLD" ] && echo "SELFTEST OK: deploy -> $a; rollback -> $b" || { echo "SELFTEST FAILED $a $b"; exit 1; };;
deploy) H=$(TZ=America/Los_Angeles date +%H%M); { [ "$H" -ge 2330 ] || [ "$H" -lt 100 ]; } && { echo "refused: 23:30-01:00 PT"; exit 1; }
  check $P || { echo "refused: check failed"; exit 1; }; install $P $BK || exit 1
  echo "DEPLOYED web_forecast_0005.py $(m8 $P/web_forecast_0005.py); rollback: bash $N/deploy_wf.sh rollback";;
rollback) restore $P $BK && echo "restored web_forecast_0005.py $(m8 $P/web_forecast_0005.py)";;
*) echo "usage: check | rehearse <day> | selftest | deploy | rollback"; exit 64;;
esac
