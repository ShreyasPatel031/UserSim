#!/bin/bash
# Full upvote-history scroll for the holdout people (DataImpulse via Chromium). Stops itself at CAP_GB of proxy traffic,
# then retries pages Cloudflare blocked once, at low parallelism.
cd /opt/scr/work
CAP_GB=${CAP_GB:-15}
sed -n '61,$p' urls.txt > main.txt
HOME=/root /opt/scr/bin/python vm_scroll_di_chromium.py ${N:-24} < main.txt 2> scroll.err | /opt/scr/bin/python parse_scroll_upvotes.py > scroll_full.jsonl &
gb() { cat pilot.jsonl p2.jsonl scroll_full.jsonl retry_out.jsonl 2>/dev/null | /opt/scr/bin/python -c "import json,sys;print(sum(json.loads(l).get('bytes',0) or 0 for l in sys.stdin)/1e9)"; }
watch() {
  while sleep 30; do
    pgrep -f vm_scroll_di_chromium >/dev/null || break
    g=$(gb); echo "$(date -u +%H:%M) $(cat scroll_full.jsonl retry_out.jsonl 2>/dev/null | wc -l) $g" >> progress.log
    if /opt/scr/bin/python -c "import sys;sys.exit(0 if $g > $CAP_GB else 1)"; then pkill -f vm_scroll_di_chromium; echo "cap hit" >> progress.log; exit 1; fi
  done
}
watch || exit 0
cat pilot.jsonl p2.jsonl scroll_full.jsonl | /opt/scr/bin/python -c "
import json,sys
for l in sys.stdin:
    r=json.loads(l)
    if r['status']!=200: print('https://www.producthunt.com/@'+r['username']+'/upvotes')" > retry_all.txt
HOME=/root /opt/scr/bin/python vm_scroll_di_chromium.py 4 < retry_all.txt 2>> scroll.err | /opt/scr/bin/python parse_scroll_upvotes.py > retry_out.jsonl &
watch
echo "done $(gb) GB" >> progress.log
