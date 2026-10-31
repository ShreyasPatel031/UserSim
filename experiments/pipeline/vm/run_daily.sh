#!/bin/bash
# Daily pipeline: runs at boot (the instance schedule starts this machine at 07:05 UTC), then powers the machine off.
#   1. pipeline.daily      launches, forecast, ranks, comments, people, personas, score, raw
#   2. pipeline.backtest   Mondays and Thursdays: backward test of the last two months
#   3. pipeline.dash_export  dashboard files to gs://.../usersim_sim/dash/ (a daily scheduled session uploads them)
#   4. pipeline.hourly     in the background all day: hourly vote snapshots of today's launches; the machine stays on
#                          until 06:55 UTC, just before the next scheduled start
# A file /home/agent/w/KEEP_ON stops the shutdown (for debugging).
set -u
# Maintenance: instance metadata skip-run=1 (settable while the machine is off) skips the run and keeps the machine on:
#   gcloud compute instances add-metadata usersim-pipeline --zone us-central1-a --metadata skip-run=1   (remove-metadata --keys skip-run after)
SKIP=$(curl -s -m 5 -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/instance/attributes/skip-run)
if [ "$SKIP" = "1" ]; then exit 0; fi
# Product Hunt's day starts at 00:00 Pacific: 07:00 UTC in summer, 08:00 UTC in winter. The schedule is 07:05 UTC, so in
# winter the machine boots at 23:05 Pacific: wait for the new day (00:05 Pacific) before fetching and forecasting.
WAIT=$(python3 -c "
import datetime as dt; from zoneinfo import ZoneInfo
n = dt.datetime.now(ZoneInfo('America/Los_Angeles'))
print(int(((n + dt.timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0) - n).total_seconds()) if n.hour == 23 else 0)")
[ "$WAIT" -gt 0 ] && sleep "$WAIT"
export PATH=/opt/exp/bin:$PATH
export PH_TOKEN=$(python3 -c "import json; print(json.load(open('/var/lib/usersim/discovery_keys.json'))['PH_TOKEN'])")
export SKIP_CLAUDE=1           # never call Claude
export LLM_PROVIDER=gemini     # launch-text scores from Gemini (backtest Oct 28: equal or better than Claude)
BUCKET=gs://usersim-bakeoff-347838016394/usersim_sim
cd /home/agent/w/experiments
LOG=/home/agent/w/logs/daily_$(date -u +%Y%m%dT%H%M).log; mkdir -p /home/agent/w/logs
# hourly vote snapshots of today's launches (launch-day forecast), alongside every step below, until just before the next run
(timeout 24h python3 -m pipeline.hourly --until 06:55 >> "${LOG%.log}_hourly.log" 2>&1; gsutil -q cp ph_predict/data/vote_snapshots/*.jsonl $BUCKET/raw/vote_snapshots/) &
HOURLY=$!
STEPS=${STEPS:-launches,snap,forecast,ranks,comments,people,personas,score,raw}
timeout 3h python3 -m pipeline.daily --only=$STEPS > "$LOG" 2>&1
timeout 2h python3 -m pipeline.backtest >> "$LOG" 2>&1
python3 -m pipeline.dash_export /tmp/usersim_dash >> "$LOG" 2>&1 && gsutil -q -m cp /tmp/usersim_dash/*.json $BUCKET/dash/
# backfill launch-page assets (logo, gallery, video links) through the official API, waiting out up to 8 rate-limit windows
(cd ph_predict && PM_WAIT_ROUNDS=8 timeout 150m python3 page_media.py >> "$LOG" 2>&1; gsutil -q cp data/page_media.jsonl $BUCKET/raw/ph_api/page_media.jsonl)
# real websites from Product Hunt's own link (route 4: Camoufox through DataImpulse), 3 h a day, every launch (name-based guesses
# were right only 8-48% of the time on a 105-launch sample), newest first
(SITES_IDS=$([ -f /home/agent/w/sites_need_ids.txt ] && echo /home/agent/w/sites_need_ids.txt) timeout 180m python3 -m pipeline.sites 100000 6 >> "$LOG" 2>&1; gsutil -q cp ph_predict/data/sites_ph.jsonl $BUCKET/raw/sites_ph.jsonl)
gsutil -q cp "$LOG" $BUCKET/logs/
wait $HOURLY   # keep the machine on for the hourly snapshots (about $3 a day)
gsutil -q cp "${LOG%.log}_hourly.log" $BUCKET/logs/
[ -f /home/agent/w/KEEP_ON ] || sudo shutdown -h now
