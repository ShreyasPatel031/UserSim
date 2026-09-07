#!/usr/bin/env bash
# Start exactly one Colab floor supervisor. Safe to re-run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
eval "$(python3 scripts/fm_baselines/gcp_auth.py --export)"
mkdir -p results/fm_baselines
PIDFILE=results/fm_baselines/supervisor.pid
LOG=results/fm_baselines/supervisor.log

if [[ -f "$PIDFILE" ]]; then
  old="$(cat "$PIDFILE" || true)"
  if [[ -n "${old}" ]] && [[ -d "/proc/${old}" ]]; then
    kill "$old" 2>/dev/null || true
    sleep 1
    kill -9 "$old" 2>/dev/null || true
  fi
fi
# also reap orphans matching the module path without matching this script
while read -r p; do
  [[ -n "$p" ]] || continue
  kill "$p" 2>/dev/null || true
done < <(pgrep -f '/scripts/fm_baselines/resilient_fm_supervisor.py' || true)
sleep 1

nohup python3 -u scripts/fm_baselines/resilient_fm_supervisor.py --floor-remaining \
  >>results/fm_baselines/supervisor.stdout.log 2>&1 &
echo $! >"$PIDFILE"
echo "STARTED $(cat "$PIDFILE")"
