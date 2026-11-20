#!/usr/bin/env bash
# Hourly exit_ip heartbeat for Population no-rotation audit (orchestrator 2026-11-20).
set -u
PY="${PY:-/opt/venv/bin/python}"
UTIL="/opt/ph/overlays/exit_ip_util.py"
[[ -f "$UTIL" ]] || UTIL="/opt/ph/reuse/exit_ip_util.py"
cd /opt/ph/reuse 2>/dev/null || cd /
export VM="${VM:-$(hostname)}"
while true; do
  [[ -x "$PY" && -f "$UTIL" ]] && "$PY" "$UTIL" log exit_ip_hourly "heartbeat" 2>>/opt/ph/reuse/supervisor.log || true
  sleep "${EXIT_IP_HEARTBEAT_SEC:-3600}"
done