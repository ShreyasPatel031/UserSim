#!/usr/bin/env bash
# Structured Pub/Sub to Population (completeness + contract).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
export AGENT_MSGS_PROJECT="${AGENT_MSGS_PROJECT:-${GCP_PROJECT:?}}"
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt")}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
M="$ART/fleet_measure.json"
ppm_c=0 ppm_r=0 ppm_a=0 vms=0
if [[ -f "$M" ]]; then
  read -r ppm_c ppm_r ppm_a vms <<<"$(python3 -c "import json; m=json.load(open('$M')); print(m.get('complete_ppm',0), m.get('rerun_ppm',0), m.get('attempt_ppm',0), m.get('vms',0))")"
fi
pct="$(python3 -c "a=float('$ppm_a') or 1; print(round(100*float('$ppm_r')/a,1))")"
msg="${1:-COMPLETENESS_COORD run=$RUN_ID utc=$(date -u +%FT%TZ). Fleet KPI window=15m: complete_ppm=$ppm_c rerun_ppm=$ppm_r (attempt=$ppm_a, rerun_pct=${pct}%). vms=$vms. Saves: PH_SAVE_B=raw/_pacetest/shared; collector full18d md5 T3OI+xr3iAvoMDMZrdryhA== pdeep FULL whole() gate. ACTION: PH_FLEET_RR_ONLY=1 — queue is Population rerun_whole_20261108T2031Z_fleetv2.txt (406 handles) until drain; no cold need_list pulls. Goal: raise Population-whole rate and complete_ppm/\$ (reruns are wasted proxy). Shreyas authorized fleet port replacement within 3 min (block→new sticky port); please release VM-gate hold on staged saves per that directive. Request: v4 audit after RR drain + hourly :20; send any new rerun_whole_*.txt for remaining incomplete. zero_incomplete still UNVERIFIED on fleet side.}"
"$ROOT/scripts/vm/ph_fleet_agent_relay.sh" population fleet-cursor "$msg"
