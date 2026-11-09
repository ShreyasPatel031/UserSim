#!/usr/bin/env bash
# Restart phsuper without a full overlay roll (after a failed mass-roll incident).
set -euo pipefail
sudo systemctl stop phsuper 2>/dev/null || true
sudo pkill -TERM -f '[p]deep.py|[p]h_batch.py' 2>/dev/null || true
sleep 2
sudo systemd-run --unit=phsuper --collect \
  -p WorkingDirectory=/opt/ph/reuse \
  -p EnvironmentFile=/opt/ph/strategy.env \
  /bin/bash -c 'bash /opt/ph/overlays/supervisor_strat.sh >> /opt/ph/reuse/supervisor.log 2>&1'
pgrep -af '[p]deep.py|[s]upervisor_strat' | head -3 || echo "starting"
