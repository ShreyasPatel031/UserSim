#!/usr/bin/env bash
# Overwrite gs://.../mailbox/from_cursor/status.json each fleet check-in (README contract).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt" 2>/dev/null)}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
M="$ART/fleet_measure.json"
[[ -f "$M" ]] || exit 0
BUCKET="${MVP_GCS_BUCKET:?}"
DEST="gs://${BUCKET}/usersim_sim/mailbox/from_cursor/status.json"
python3 - "$M" "$RUN_ID" <<'PY' | gcloud storage cp - "$DEST" >/dev/null
import json, sys, datetime
m=json.load(open(sys.argv[1]))
run=sys.argv[2]
slots=[]
for s in m.get("slots") or []:
    if s.get("state") == "probe_fail":
        continue
    slots.append({
        "slot": s.get("slot"),
        "state": s.get("state"),
        "ppm_complete": s.get("ppm_complete"),
        "port": s.get("port"),
        "batch": s.get("batch"),
    })
out={
    "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "agent": "fleet-cursor",
    "run_id": run,
    "vms": m.get("vms"),
    "complete_ppm_15m": m.get("complete_ppm"),
    "attempt_ppm_15m": m.get("attempt_ppm"),
    "pkg_md5": "uYYdW17hoPBJjpMGoR7lKw==",
    "staging": "raw/_pacetest/shared",
    "slots_summary": slots,
    "mailbox": "usersim_sim/mailbox/from_cursor/",
}
print(json.dumps(out, indent=2))
PY
