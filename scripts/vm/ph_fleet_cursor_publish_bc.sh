#!/usr/bin/env bash
# Publish this Cloud Agent bc id so Pub/Sub wake bridge can steer the right run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
BC_ID="${FLEET_CURSOR_BC_ID:-${CURSOR_CONVERSATION_ID:-}}"
[[ -n "$BC_ID" ]] || exit 0
BUCKET="${MVP_GCS_BUCKET:?}"
DEST="gs://${BUCKET}/usersim_sim/mailbox/from_cursor/cursor_agent.json"
BC_ID="$BC_ID" python3 - <<'PY' | gcloud storage cp - "$DEST" >/dev/null
import json, os, datetime
bc = os.environ["BC_ID"]
out = {
    "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "agent": "fleet-cursor",
    "bc_id": bc,
    "note": "Used by fleet-cursor-wake Cloud Run (Pub/Sub push → Cursor API steer).",
}
print(json.dumps(out, indent=2))
PY
