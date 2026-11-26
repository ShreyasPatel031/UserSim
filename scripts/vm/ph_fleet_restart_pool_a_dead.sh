#!/usr/bin/env bash
# Start phsuper on Pool A slots that measure as dead (batch=false), excluding live + Pool B.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID,,}"
MEASURE="$ART/fleet_measure.json"
[[ -f "$MEASURE" ]] || exit 0
LIVE="${FLEET_LIVE_SLOTS:-39}"
POOL_B="${FLEET_POOL_B_PINNED_SLOTS:-32 40 42 44 45}"
mapfile -t dead < <(python3 - "$MEASURE" "$LIVE" "$POOL_B" <<'PY'
import json, os, sys
m = json.load(open(sys.argv[1]))
live = set(sys.argv[2].split())
pool_b = set(sys.argv[3].split())
out = []
for s in m.get("slots") or []:
    slot = str(s.get("slot") or "")
    if slot in live or slot in pool_b:
        continue
    if (s.get("state") or "") == "dead" and not s.get("batch"):
        out.append(slot)
print(" ".join(sorted(out, key=int)))
PY
)
[[ -n "${dead[*]:-}" ]] || { echo "pool_a_dead_restart none"; exit 0; }
chmod +x "$ROOT/scripts/vm/ph_fleet_inplace_restart_slots.sh"
PACE_FLEET_RUN_ID="${RUN_ID,,}" bash "$ROOT/scripts/vm/ph_fleet_inplace_restart_slots.sh" "${dead[@]}"