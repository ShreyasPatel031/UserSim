#!/bin/bash
# Bundle 11 (pipeline change: needs Shreyas's direct approval): no caps / no silent drops. Copies files only; starts and stops
# nothing. Refuses to run 00:05-01:00 PT. Works whether or not bundle 10 is deployed (picks the matching daily.py).
# usage on usersim-pipeline:   bash deploy_b11.sh pipeline <dir holding experiments/...>
#        for the scraper VM:   bash deploy_b11.sh scraper  <dir holding experiments/...>   (replaces gs://.../scrapers_deploy/daily.py)
#        for vm_leaderboard:   bash deploy_b11.sh leaderboard <dir holding experiments/...> (on the VM that runs it, ~/w/experiments)
# Rollback: tar xf $W/backup_b11/before_<part>.tar -C <same root>   (scraper: gsutil cp $W/backup_b11/scrapers_daily.py back)
set -euo pipefail
PART=${1:?pipeline|scraper|leaderboard}; SRC=${2:?dir}; W=/home/agent/w; X=$W/experiments
Pd=$SRC/experiments/pipeline_patches/20261113_no_caps; B=gs://usersim-bakeoff-347838016394/usersim_sim
export PATH=/opt/exp/bin:$PATH
H=$(TZ=America/Los_Angeles date +%H%M); [ "$H" -lt 0005 ] || [ "$H" -ge 0100 ] || { echo "inside 00:05-01:00 PT: not deploying"; exit 1; }
m() { md5sum < "$1" | cut -c1-8; }
mkdir -p $W/backup_b11
case "$PART" in
pipeline)
  cur=$(m $X/pipeline/daily.py)
  curw=$(m $X/pipeline/warehouse.py)
  if [ "$cur" = 27f0578d ] && [ "$curw" = c89671dc ]; then NEW=$Pd/daily.py; WANT=03c9fa7b; NEWW=$Pd/warehouse.py; WANTW=a2d08cdf
  elif [ "$cur" = 6e80e47e ] && [ "$curw" = d5a50870 ]; then NEW=$Pd/daily_over_b10.py; WANT=6392b6be; NEWW=$Pd/warehouse_over_b10.py; WANTW=6c9d2a83
  else echo "deployed daily.py ($cur) / warehouse.py ($curw) are neither pre-b10 (27f0578d / c89671dc) nor b10 (6e80e47e / d5a50870): rebase the patch first"; exit 1; fi
  test "$(m $NEW)" = "$WANT" && test "$(m $NEWW)" = "$WANTW" || { echo "source files are not the b11 versions"; exit 1; }
  (cd $X && tar cf $W/backup_b11/before_pipeline.tar pipeline/daily.py pipeline/warehouse.py)
  cp $NEW $X/pipeline/daily.py.new && mv $X/pipeline/daily.py.new $X/pipeline/daily.py
  cp $NEWW $X/pipeline/warehouse.py.new && mv $X/pipeline/warehouse.py.new $X/pipeline/warehouse.py
  cp $Pd/queue_unpulled_commenters.py $X/pipeline/queue_unpulled_commenters.py
  cd $X && python3 -c "
import pipeline.daily as D, pipeline.queue_unpulled_commenters as Q, inspect
assert not hasattr(D, 'PERSON_CAP') and D.PERSON_BUDGET > 0
src = inspect.getsource(D)
assert 'f.unlink()' not in src and 'os.replace(new, old)' in src
assert 'queue_write(\"scroll_deeper\"' in src and 'has_next' in src
assert 'def people_from_store' in src and 'PEOPLE_SRC\", \"store_v3\"' in src and 'events_unmatched' in src
import pipeline.warehouse as Wh
assert 'events_unmatched' in Wh.KEYS and 'follows_unmatched' in Wh.KEYS
print('imports ok')"
  test "$(m $X/pipeline/daily.py)" = "$WANT" && test "$(m $X/pipeline/warehouse.py)" = "$WANTW" && echo "deploy ok: b11 pipeline (daily $WANT, warehouse $WANTW)";;
scraper)
  gsutil -q cp $B/scrapers_deploy/daily.py $W/backup_b11/scrapers_daily.py
  test "$(m $W/backup_b11/scrapers_daily.py)" = 2f661bb4 || { echo "scrapers_deploy/daily.py is not the expected version"; exit 1; }
  test "$(m $Pd/scrapers_daily.py)" = 2a808470 || { echo "source file is not the b11 version"; exit 1; }
  python3 -c "import ast; ast.parse(open('$Pd/scrapers_daily.py').read())"
  gsutil -q cp $Pd/scrapers_daily.py $B/scrapers_deploy/daily.py.new && gsutil -q mv $B/scrapers_deploy/daily.py.new $B/scrapers_deploy/daily.py
  echo "deploy ok: b11 scraper (2a808470); the scraper VM picks it up at its next start (run.sh unchanged; set N is no longer used, HOURS=24 default)";;
leaderboard)
  test "$(m $X/ph_predict/vm_leaderboard.py)" = e9f4ef72 || { echo "vm_leaderboard.py is not the expected version"; exit 1; }
  (cd $X && tar cf $W/backup_b11/before_leaderboard.tar ph_predict/vm_leaderboard.py)
  cp $Pd/vm_leaderboard.py $X/ph_predict/vm_leaderboard.py
  test "$(m $X/ph_predict/vm_leaderboard.py)" = 402b1051 && echo "deploy ok: b11 leaderboard (402b1051)";;
*) echo "unknown part"; exit 2;;
esac
