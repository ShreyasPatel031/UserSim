#!/usr/bin/env bash
set -uo pipefail

cd "${HOME}/usersim"
mkdir -p pilot_results pilot_logs

queries=(
  "motivational videos"
  "productivity videos"
  "cooking recipes"
  "workout at home"
  "lo-fi music"
  "science documentaries"
  "personal finance tips"
  "learn python tutorial"
)

state="secrets/site_states/www.youtube.com.json"
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "$started" > pilot_results/wave_started_at.txt

pids=()
for i in "${!queries[@]}"; do
  env USE_GCE_ADC=1 PYTHONPATH=src \
    .venv/bin/python scripts/vm/youtube_parallel_auth_smoke.py \
      --query "${queries[$i]}" --state "$state" --out "pilot_results/worker_${i}.json" \
      > "pilot_logs/worker_${i}.log" 2>&1 &
  pids+=("$!")
done

rc=0
for pid in "${pids[@]}"; do
  wait "$pid" || rc=1
done

finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "$finished" > pilot_results/wave_finished_at.txt
PYTHONPATH=src .venv/bin/python - <<'PY'
import json
from pathlib import Path

rows=[]
for p in sorted(Path('pilot_results').glob('worker_*.json')):
    try: rows.append(json.loads(p.read_text()))
    except Exception as exc: rows.append({'ok':False,'reason':f'unreadable:{exc}','file':p.name})
summary={
    'workers_expected':8,
    'workers_reported':len(rows),
    'workers_ok':sum(bool(r.get('ok')) for r in rows),
    'workers_signed_in':sum(int((r.get('signed_in_verify') or r.get('verify') or {}).get('avatar_count',0)>0) for r in rows),
    'results':rows,
}
Path('pilot_results/summary.json').write_text(json.dumps(summary,indent=2,default=str))
print(json.dumps({k:v for k,v in summary.items() if k!='results'},indent=2))
PY
exit "$rc"
