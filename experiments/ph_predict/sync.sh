#!/bin/bash
# every 2 min: push new PH days to the VM resolver, pull resolved sites back, score new days with the LLM
cd "$(dirname "$0")"
while true; do
  scp -q data/days/*.json vm:php/data/days/
  ssh vm 'cd ~/php; pgrep -f "^/opt/usersim/venv/bin/python resolve_sites" >/dev/null || (NO_WB=1 setsid nohup /opt/usersim/venv/bin/python resolve_sites.py 64 >> sites.log 2>&1 < /dev/null &)'
  ssh vm 'gzip -1 -c ~/php/data/sites.jsonl' | gunzip > data/sites.jsonl.tmp && mv data/sites.jsonl.tmp data/sites.jsonl
  pgrep -f "[l]lm.py pitch" >/dev/null || (setsid nohup python3 llm.py pitch 4 >> llm_pitch.log 2>&1 < /dev/null &)
  pgrep -f "[l]lm.py site" >/dev/null || (setsid nohup python3 llm.py site 3 >> llm_site.log 2>&1 < /dev/null &)
  pgrep -f "[l]lm.py brand" >/dev/null || (setsid nohup python3 llm.py brand 3 >> llm_brand.log 2>&1 < /dev/null &)
  echo "sync $(date -u +%T) days=$(ls data/days | wc -l) sites=$(wc -l < data/sites.jsonl)" >> sync.log
  sleep 120
done
