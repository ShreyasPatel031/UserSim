#!/bin/bash
# hunter_reach_0005 shadow file (orchestrator 08:15Z Nov 17): e5_follow_run.sh (12.8's nightly e5 job) gains a hunter step + hunter_reach.py.
# usage (VM, agent): bash deploy_hunter_reach.sh rehearse <D> | deploy | rollback.  Base e5_follow_run.sh 6ca90ed5 required.
set -u; W=/home/agent/w; N=$(cd "$(dirname "$0")" && pwd); P=$W/tw/experiments/ph_predict; BK=$W/backup_hunter_reach; PY=/opt/exp/bin/python3
m8() { [ -e "$1" ] && md5sum < "$1" | cut -c1-8 || echo none; }
case "${1:-}" in
rehearse)   # end to end on a real day, DRY: scratch copy of the tw code, scratch work dir, gsutil stub refuses uploads
  D=${2:?day}; T=$(mktemp -d); mkdir -p $T/bin $T/x/experiments; cp -r $W/tw/experiments/pipeline $T/x/experiments/; mkdir -p $T/x/experiments/ph_predict
  cp $P/*.py $T/x/experiments/ph_predict/ 2>/dev/null; cp $N/hunter_reach.py $N/e5_follow_run.sh $T/x/experiments/ph_predict/
  REAL=$(command -v gsutil); printf '#!/bin/bash\nlast="${@: -1}"\nfor a in "$@"; do case "$a" in cp|rsync|mv) case "$last" in gs://*) echo "DRY: upload to $last refused" >&2; exit 0;; esac;; rm) exit 0;; esac; done\nexec %s "$@"\n' "$REAL" > $T/bin/gsutil; chmod +x $T/bin/gsutil
  mkdir -p $T/work/s; cp $W/tw/e5/e5f/s/salt $T/work/s/salt; for sd in $W/tw/e5/e5f/store_store_v3_*; do ln -s $sd $T/work/$(basename $sd); done; cp $W/tw/e5/e5f/follow_shadow.py $T/work/
  out=$(cd $T/x/experiments/ph_predict && PATH=$T/bin:/opt/exp/bin:$PATH USERSIM_CACHE=$W/tw/cache bash ./e5_follow_run.sh $D $T/work 2>&1); rc=$?
  echo "$out" | grep -E "hunter|DRY|wrote|exists|no 00:05" | head -6
  f=$T/work/hunter_reach_$D.json; [ -s $f ] && $PY -c "import json,sys; d=json.load(open(sys.argv[1])); L=d['launches']; print(json.dumps({'day': d['day'], 'launches': len(L), 'eligible_people': d['eligible_people'], 'hunters_in_store': sum(1 for r in L if r['hunter_in_store']), 'with_followers': sum(1 for r in L if (r['held_followers_pre'] or 0) > 0)}))" $f || { echo "REHEARSAL FAILED: no hunter_reach file"; rm -rf "$T"; exit 1; }
  rm -rf "$T"; echo "REHEARSAL PASSED"; exit 0;;
deploy)
  H=$(TZ=America/Los_Angeles date +%H%M); { [ "$H" -ge 2330 ] || [ "$H" -lt 100 ]; } && { echo "refused: 23:30-01:00 PT"; exit 1; }
  [ "$(m8 $P/e5_follow_run.sh)" = 6ca90ed5 ] || { echo "refused: e5_follow_run.sh $(m8 $P/e5_follow_run.sh) != 6ca90ed5"; exit 1; }
  mkdir -p $BK && cp -p $P/e5_follow_run.sh $BK/e5_follow_run.sh.6ca90ed5
  cp $N/hunter_reach.py $P/hunter_reach.py.new && mv $P/hunter_reach.py.new $P/hunter_reach.py; cp $N/e5_follow_run.sh $P/e5_follow_run.sh.new && mv $P/e5_follow_run.sh.new $P/e5_follow_run.sh
  bash -n $P/e5_follow_run.sh && (cd $P && $PY -c "import ast,sys; ast.parse(open('hunter_reach.py').read())") || { cp -p $BK/e5_follow_run.sh.6ca90ed5 $P/e5_follow_run.sh; rm -f $P/hunter_reach.py; echo "check failed: rolled back"; exit 1; }
  echo "DEPLOYED e5_follow_run.sh $(m8 $P/e5_follow_run.sh) + hunter_reach.py $(m8 $P/hunter_reach.py); rollback: bash $N/deploy_hunter_reach.sh rollback";;
rollback) cp -p $BK/e5_follow_run.sh.6ca90ed5 $P/e5_follow_run.sh && rm -f $P/hunter_reach.py && echo "rolled back";;
*) echo "usage: rehearse <D> | deploy | rollback"; exit 64;;
esac
