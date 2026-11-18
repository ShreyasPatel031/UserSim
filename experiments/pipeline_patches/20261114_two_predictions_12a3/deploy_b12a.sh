#!/bin/bash
# Bundle 12a (needs Shreyas's direct word: it changes the VM crontab and adds one Product Hunt API read a day, 03:45 PT): the two published
# predictions written by code on usersim-pipeline. Copies files to /home/agent/w/tw12a and adds ONE crontab line (a minute tick) in its own
# exactly-matched block; any other block (bundle 12's, the @reboot line) is left as it is, in either deploy order (review B2).
# Every deploy and rollback first saves a timestamped crontab backup; rollback removes only this block and never restores a whole file (B3).
# Refuses 00:05-01:00 PT (deploy only; rollback always runs). Checks md5s. After install it waits for two ticks to prove cron fires and the Pacific gate works (B4).
# usage (on the VM):  bash deploy_b12a.sh <this folder>      rollback: bash deploy_b12a.sh rollback      full removal: bash deploy_b12a.sh remove
# ATOMIC SWAP (E5 pre-flight 20:21Z Nov 14): ~/w/tw12a is a symlink to a versioned tree ~/w/tw12a.d/<stamp>; a deploy flips it with one
# rename (ln -sfn tmp + mv -T), so a kill at any point leaves either the old or the new tree live, never none. rollback flips back to the
# previous tree (cron block kept, so the two predictions keep being written); only `remove` deletes the block and moves the tree away.
set -euo pipefail
W=/home/agent/w; T=$W/tw12a; BK=$W/backup_b12a; mkdir -p $BK; export PATH=/opt/exp/bin:$PATH
STAMP=$(date -u +%Y%m%dT%H%M%S); crontab -l > $BK/crontab.$STAMP 2>/dev/null || true
strip() { sed '/^# BEGIN usersim-b12a$/,/^# END usersim-b12a$/d'; }
DIRS=$W/tw12a.d; mkdir -p $DIRS
flip() { ln -sfn "$1" $W/tw12a.tmp && mv -Tf $W/tw12a.tmp $T; }
if [ "${1:-}" = rollback ] && [ -s $DIRS/previous ] && [ -d "$(cat $DIRS/previous)" ]; then
  P_=$(cat $DIRS/previous); C_=$(readlink -f $T 2>/dev/null || true); flip "$P_"; echo "rolled back: tw12a -> $P_ (was $C_); cron block kept"
  [ -n "$C_" ] && echo "$C_" > $DIRS/rolled_back_from; rm -f $DIRS/previous
  # the weights pin follows the restored tree (E5 pre-flight 2): pinned only if the restored tree carries the fixed-prior weights
  RW=$(md5sum < $P_/hybrid_vmonly_P345_20261114.json 2>/dev/null | cut -c1-8); if [ "$RW" = b8a59cdd ]; then echo b8a59cdd > $DIRS/weights_pin; else rm -f $DIRS/weights_pin; fi
  echo "weights pin now: $(cat $DIRS/weights_pin 2>/dev/null || echo none)"; exit 0
fi
if [ "${1:-}" = rollback ]; then   # no previous tree: refuse (a second rollback must never remove 12a); full removal only via `remove`
  echo "rollback: no previous tree recorded in $DIRS/previous; refusing (use 'remove' to take 12a off the VM)"; exit 1
fi
if [ "${1:-}" = remove ]; then   # explicit full removal
  crontab -l 2>/dev/null | strip > $BK/crontab.after_rollback.$STAMP
  grep -q "run_daily.sh" $BK/crontab.after_rollback.$STAMP || { echo "rollback result lacks the @reboot run_daily line: refusing"; exit 1; }
  crontab $BK/crontab.after_rollback.$STAMP && echo "b12a block removed (backup $BK/crontab.$STAMP)"
  [ -d $T ] && mv $T $BK/tw12a.removed_$STAMP; exit 0
fi
# time guard below the rollback branch: rollback is always allowed (orchestrator 12:36Z Nov 14)
H=$(TZ=America/Los_Angeles date +%H%M); [ "$H" -lt 0005 ] || [ "$H" -ge 0100 ] || { echo "inside 00:05-01:00 PT: not deploying"; exit 1; }
[ "$(id -un)" = agent ] || { echo "run as user agent (the crontab owner): not deploying"; exit 1; }
S=${1:?folder}; m() { md5sum < "$1" | cut -c1-8; }
declare -A WANT=( [two_predictions.py]=bcbaf6b6 [import_gate.py]=be4891b9 [lineup_reread.py]=4fa6b418 [recorder_extra.py]=c1231100 [run.sh]=5cd8b9e5 [tick.sh]=d446e816 [sched12a.txt]=4cec4d5e [cron12a.txt]=0e2c7f4d [hybrid_vmonly_P345_20261114.json]=b8a59cdd )
# weights pin (written by install_fixedprior_weights.sh): once the fixed-prior weights are live, a redeploy must carry them, never revert to 16912cd6
LIVEW=$(md5sum < $T/hybrid_vmonly_P345_20261114.json 2>/dev/null | cut -c1-8 || true)
# the LIVE tree's weights count as a pin too (covers a kill between the flip and the pin write)
[ "$LIVEW" = b8a59cdd ] && [ "${WANT[hybrid_vmonly_P345_20261114.json]}" != b8a59cdd ] && { echo "live tree carries the fixed-prior weights b8a59cdd; this folder carries ${WANT[hybrid_vmonly_P345_20261114.json]}: refusing"; exit 1; }
[ -s $DIRS/weights_pin ] && [ "${WANT[hybrid_vmonly_P345_20261114.json]}" != "$(cat $DIRS/weights_pin)" ] && { echo "weights pin $(cat $DIRS/weights_pin) is live; this folder carries ${WANT[hybrid_vmonly_P345_20261114.json]}: refusing (would revert the fixed-prior weights)"; exit 1; }
# 12a.3 carries the fixed-prior weights and labels: only after the today-rows fix is live (its marker exists)
[ -s $W/today_rows_fix.json ] || { echo "today-rows marker ~/w/today_rows_fix.json missing: deploy the today-rows fix first (safe order)"; exit 1; }
for f in "${!WANT[@]}"; do [ "$(m $S/$f)" = "${WANT[$f]}" ] || { echo "$f md5 $(m $S/$f) != ${WANT[$f]}"; exit 1; }; done
[ -s $BK/crontab.$STAMP ] || { echo "current crontab empty or unreadable: refusing (expected the @reboot run_daily line)"; exit 1; }
# stage, check and gate in tw12a.stage; the live tree is replaced only after every check passes
N=$DIRS/$STAMP; mkdir -p $N; for f in "${!WANT[@]}"; do cp $S/$f $N/$f; done
python3 -c "import ast; [ast.parse(open('$N/'+f).read()) for f in ('two_predictions.py', 'recorder_extra.py', 'import_gate.py', 'lineup_reread.py')]"; bash -n $N/run.sh; bash -n $N/tick.sh
(cd $W/experiments && env -u PYTHONPATH /opt/exp/bin/python3 -c "from pipeline import hourly; assert hasattr(hourly, '_snapshot') and hasattr(hourly, 'pacific_day')")
# HARD IMPORT GATE (orchestrator 09:12Z Nov 14): every module each job imports, exactly as cron runs it: user agent, cron's cwd ($HOME) for
# two_predictions, w/experiments for recorder_extra (as run.sh does), PYTHONPATH unset, /opt/exp/bin/python3. Any ImportError aborts.
(cd /home/agent && env -u PYTHONPATH /opt/exp/bin/python3 $N/import_gate.py $N/two_predictions.py) || { echo "import gate failed: two_predictions: not deploying"; exit 1; }
(cd $W/experiments && env -u PYTHONPATH /opt/exp/bin/python3 $N/import_gate.py $N/recorder_extra.py) || { echo "import gate failed: recorder_extra: not deploying"; exit 1; }
(cd $W/experiments/ph_predict && env -u PYTHONPATH /opt/exp/bin/python3 $N/import_gate.py $N/lineup_reread.py) || { echo "import gate failed: lineup_reread: not deploying"; exit 1; }
if [ -d $T ] && [ ! -L $T ]; then   # first deploy of the symlink layout: the old real tree becomes a versioned dir (brief, before any flip)
  tar cf $BK/tw12a_before_$STAMP.tar -C $W tw12a; mv $T $DIRS/legacy_$STAMP && ln -s $DIRS/legacy_$STAMP $T; fi
[ -L $T ] && readlink -f $T > $DIRS/previous
flip $N
( crontab -l 2>/dev/null | strip; cat $T/cron12a.txt ) > $BK/crontab.new.$STAMP
grep -q "run_daily.sh" $BK/crontab.new.$STAMP || { echo "new crontab lacks the @reboot run_daily line: not installing"; exit 1; }
crontab $BK/crontab.new.$STAMP
# prove the tick: cron runs it every minute; last_tick must change within ~2 min and show a Pacific time
rm -f $T/last_tick; for i in $(seq 1 26); do [ -s $T/last_tick ] && break; sleep 5; done
[ -s $T/last_tick ] || { echo "no tick within 130 s: rolling back"; bash $0 rollback; exit 1; }
echo "deploy ok: b12a; crontab $(crontab -l | md5sum | cut -c1-8); tick: $(cat $T/last_tick); UTC now $(date -u +%H:%M)"
