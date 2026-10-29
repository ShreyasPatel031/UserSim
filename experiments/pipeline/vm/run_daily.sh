#!/bin/bash
# Daily pipeline: runs at boot (the instance schedule starts this machine at 07:05 UTC), then powers the machine off.
#   1. pipeline.daily      launches, forecast, ranks, comments, people, personas, score, raw
#   2. pipeline.backtest   Mondays and Thursdays: backward test of the last two months
#   3. pipeline.dash_export  dashboard files to gs://.../usersim_sim/dash/ (a daily scheduled session uploads them)
# A file /home/agent/w/KEEP_ON stops the shutdown (for debugging).
set -u
# A file /home/agent/w/SKIP_NEXT skips one boot's run (for maintenance), then is removed.
if [ -f /home/agent/w/SKIP_NEXT ]; then rm -f /home/agent/w/SKIP_NEXT; exit 0; fi
export PATH=/opt/exp/bin:$PATH
export PH_TOKEN=$(python3 -c "import json; print(json.load(open('/var/lib/usersim/discovery_keys.json'))['PH_TOKEN'])")
export SKIP_CLAUDE=1           # never call Claude
export LLM_PROVIDER=gemini     # launch-text scores from Gemini (backtest Oct 28: equal or better than Claude)
BUCKET=gs://usersim-bakeoff-347838016394/usersim_sim
cd /home/agent/w/experiments
LOG=/home/agent/w/logs/daily_$(date -u +%Y%m%dT%H%M).log; mkdir -p /home/agent/w/logs
STEPS=${STEPS:-launches,snap,forecast,ranks,comments,people,personas,score,raw}
timeout 3h python3 -m pipeline.daily --only=$STEPS > "$LOG" 2>&1
timeout 2h python3 -m pipeline.backtest >> "$LOG" 2>&1
python3 -m pipeline.dash_export /tmp/usersim_dash >> "$LOG" 2>&1 && gsutil -q -m cp /tmp/usersim_dash/*.json $BUCKET/dash/
gsutil -q cp "$LOG" $BUCKET/logs/
[ -f /home/agent/w/KEEP_ON ] || sudo shutdown -h now
