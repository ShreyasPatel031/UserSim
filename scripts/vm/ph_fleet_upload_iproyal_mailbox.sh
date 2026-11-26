#!/usr/bin/env bash
# Publish iproyal ledger + assignments each 15m tick (antigravity / fleet-cursor contract).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
BUCKET="${MVP_GCS_BUCKET:?}"
DEST="gs://${BUCKET}/usersim_sim/mailbox/from_cursor"
mkdir -p "$ART/from_cursor"
if [[ -f "$ART/iproyal_rotate.log" ]]; then
  cp "$ART/iproyal_rotate.log" "$ART/from_cursor/iproyal_rotate.log.full"
fi
python3 - "$ART" <<'PY'
import json, sys
from pathlib import Path
from datetime import datetime, timezone
art = Path(sys.argv[1])
assign = art / "iproyal_assignments.json"
meta = {"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_iproyal_rotate_utc": None, "slots": 0}
if assign.is_file():
    j = json.loads(assign.read_text())
    slots = j.get("slots") or {}
    meta["slots"] = len(slots)
    times = [s.get("last_rotate_utc") for s in slots.values() if s.get("last_rotate_utc")]
    if times:
        meta["last_iproyal_rotate_utc"] = max(times)
(art / "iproyal_rotate_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
PY
[[ -f "$ART/iproyal_assignments.json" ]] && \
  gcloud storage cp "$ART/iproyal_assignments.json" "${DEST}/iproyal_assignments.json"
[[ -f "$ART/from_cursor/iproyal_rotate.log.full" ]] && \
  gcloud storage cp "$ART/from_cursor/iproyal_rotate.log.full" "${DEST}/iproyal_rotate.log.full"
[[ -f "$ART/iproyal_rotate_meta.json" ]] && \
  gcloud storage cp "$ART/iproyal_rotate_meta.json" "${DEST}/iproyal_rotate_meta.json"
echo "iproyal_mailbox_upload last=$(python3 -c "import json;print(json.load(open('$ART/iproyal_rotate_meta.json'))['last_iproyal_rotate_utc'])")"