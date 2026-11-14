#!/bin/bash
# E5 website writers for the VM cron (bundle 12). No LLM, no git at run time. Idempotent (re-running rewrites the same files).
#   bash run.sh <job> [day]   job: track_record | prob_0005 | prob_prereveal | period | period_score | held_team_predict | held_team_score
#   day defaults: prob_0005 / prob_prereveal / held_team_predict -> today PT; period / held_team_score -> yesterday PT.
# ASSETS (default $HOME/e5_assets) is synced from gs://usersim-bakeoff-347838016394/usersim_sim/tmp/e5/vm_writers/assets/ and the 2025 lists;
# held_team_* also need the person-id salt at $ASSETS/early/salt (the same salt the store builders use; NOT in the bundle).
set -u; HERE="$(cd "$(dirname "$0")" && pwd)"; JOB=${1:?job}; ASSETS=${ASSETS:-$HOME/e5_assets}; B=gs://usersim-bakeoff-347838016394/usersim_sim
TODAY=$(TZ=America/Los_Angeles date +%F); YDAY=$(TZ=America/Los_Angeles date -d yesterday +%F); LOG=${LOG:-$ASSETS/e5_writers.log}
mkdir -p "$ASSETS/a2x" "$ASSETS/ph2025"
gsutil -q -m rsync "$B/tmp/e5/vm_writers/assets/a2x/" "$ASSETS/a2x/" && gsutil -q -m rsync "$B/raw/ph_history/2025/" "$ASSETS/ph2025/" || { echo "$(date -u +%FT%TZ) $JOB FAIL asset sync" | tee -a "$LOG"; exit 2; }
miss=""; for f in a2x/X.parquet; do [ -s "$ASSETS/$f" ] || miss="$miss $f"; done
case "$JOB" in held_team_*) [ -s "$ASSETS/early/salt" ] || miss="$miss early/salt";; esac
[ -n "$miss" ] && { echo "$(date -u +%FT%TZ) $JOB FAIL inputs missing:$miss" | tee -a "$LOG"; exit 3; }
cd "$HERE/simlab"; export PYTHONPATH="$HERE:${PYTHONPATH:-}"
period_score_run() { local r=0   # week on Sundays, month on the month's last day; both on a Sunday month end; rc = first failure
  [ "$(date -d "$D" +%u)" = 7 ] && { python period_score.py week "$D" "$ASSETS" || r=$?; }
  [ "$(date -d "$D + 1 day" +%d)" = 01 ] && { python period_score.py month "$D" "$ASSETS" || { m=$?; [ $r = 0 ] && r=$m; }; }
  return $r; }
case "$JOB" in
  track_record)      cmd="python track_record.py $ASSETS";;
  prob_0005)         cmd="python prob_writer.py 0005 ${2:-$TODAY} $ASSETS";;
  prob_prereveal)    cmd="python prob_writer.py prereveal ${2:-$TODAY} $ASSETS";;
  period)            cmd="python period_writer.py ${2:-$YDAY} $ASSETS";;
  period_score)      D=${2:-$YDAY}; cmd=period_score_run;;   # a function: "$cmd" with ';' inside never ran the month (bug sweep 6, repro_B6.sh)
  held_team_predict) cmd="python held_team_shadow.py predict ${2:-$TODAY} $ASSETS";;
  held_team_score)   cmd="python held_team_shadow.py score ${2:-$YDAY} $ASSETS";;
  *) echo "unknown job $JOB"; exit 64;;
esac
out=$($cmd 2>&1); rc=$?
echo "$(date -u +%FT%TZ) $JOB rc=$rc inputs present (a2x/X.parquet, ph2025, frozen tables) | $(echo "$out" | tail -1 | cut -c1-300)" | tee -a "$LOG"
exit $rc
