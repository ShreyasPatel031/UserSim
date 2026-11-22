#!/usr/bin/env bash
# Page fleet-cursor (Pub/Sub → steer) when throughput is bad. Does NOT recover VMs itself.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
MEASURE="$ART/fleet_measure.json"
COOLDOWN_SEC="${FLEET_AGENT_STALL_WAKE_COOLDOWN_SEC:-1800}"
STAMP="$ART/last_agent_stall_wake.utc"
[[ -f "$MEASURE" ]] || exit 0
# shellcheck source=/dev/null
source "${PACE_ENV_FILE:-$ART/pace.env}" 2>/dev/null || true
export AGENT_MSGS_PROJECT="${AGENT_MSGS_PROJECT:-${GCP_PROJECT:-}}"
[[ -n "${AGENT_MSGS_PROJECT}" ]] || exit 0

msg="$(python3 - "$MEASURE" "$STAMP" "$COOLDOWN_SEC" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

measure_path, stamp_path, cooldown_s = sys.argv[1:4]
cooldown_s = int(cooldown_s)
m = json.loads(Path(measure_path).read_text())
ppm = float(m.get("complete_ppm") or 0)
attempt = float(m.get("attempt_ppm") or 0)
refresh = float(m.get("upvote_refresh_ppm_15m") or 0)
productive = int(m.get("productive_vms") or 0)
active = int(m.get("active_vms") or 0)
dead = sum(1 for s in m.get("slots") or [] if s.get("state") == "dead")
stale = sum(1 for s in m.get("slots") or [] if s.get("state") == "stale")

if not (ppm < 0.05 and attempt < 0.15 and productive <= 3):
    sys.exit(2)

stamp = Path(stamp_path)
now = datetime.now(timezone.utc)
if stamp.is_file():
    try:
        t0 = datetime.fromisoformat(stamp.read_text().strip().replace("Z", "+00:00"))
        if (now - t0).total_seconds() < cooldown_s:
            sys.exit(3)
    except Exception:
        pass
stamp.write_text(now.strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")
print(
    f"[fleet-stall-wake] throughput flat: complete_ppm={ppm:.3f} attempt_ppm={attempt:.3f} "
    f"refresh_ppm={refresh:.2f} productive_vms={productive} active_vms={active} dead={dead} stale={stale}. "
    "Investigate and act (wake pdeep slots, deploy stacks GQL fix) — do not only ACK or cite Population. "
    "LIVE_PRIORITY_HOLD: no historical VM scale-up unless live critical_stale."
)
PY
)" || exit 0

chmod +x "$ROOT/scripts/vm/ph_fleet_agent_stall_wake.sh"
bash "$ROOT/scripts/vm/ph_fleet_agent_relay.sh" fleet-cursor fleet-stall-wake "$msg"
echo "agent_stall_wake sent"