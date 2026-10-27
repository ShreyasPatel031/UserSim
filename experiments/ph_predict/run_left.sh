#!/bin/bash
# Remaining holdout people's upvote histories back to Sep 1 (DataImpulse via Chromium, 4 browsers on the main VM).
# Stops itself at CAP_GB of counted traffic, or when the proxy reports exhausted traffic.
cd /home/agent/php
CAP_GB=${CAP_GB:-6}
{ sed -n 6,25p urls_left.txt; sed -n '46,$p' urls_left.txt; } > left_main.txt
HOME=/root OLD_IDS=old_ids.txt /opt/usersim/venv/bin/python vm_scroll_lean.py 4 < left_main.txt 2> left.err | /opt/usersim/venv/bin/python parse_scroll_upvotes.py > scroll_left.jsonl &
while sleep 60; do
  pgrep -f vm_scroll_lean >/dev/null || break
  read n g bad <<< $(/opt/usersim/venv/bin/python -c "
import json
R=[json.loads(l) for l in open('scroll_left.jsonl')]
print(len(R), sum(r.get('bytes',0) or 0 for r in R)/1e9, sum(1 for r in R[-20:] if r['status']==0))")
  echo "$(date -u +%H:%M) $n $g bad_last20=$bad" >> left_progress.log
  if /opt/usersim/venv/bin/python -c "import sys;sys.exit(0 if $g > $CAP_GB or $bad >= 15 else 1)"; then pkill -f vm_scroll_lean; echo "stopped: cap or proxy failing" >> left_progress.log; break; fi
done
echo "done" >> left_progress.log
