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
python3 - "$M" "$RUN_ID" "$GCP_PROJECT" "${PACE_SERVICE_ACCOUNT:-}" <<'PY' | gcloud storage cp - "$DEST" >/dev/null
import json, subprocess, sys, datetime
m=json.load(open(sys.argv[1]))
run=sys.argv[2]
proj, sa = sys.argv[3], sys.argv[4]
gce_running = gce_terminated = None
if proj:
    gc = ["gcloud", "--format=value(status)"]
    if sa:
        gc = ["gcloud", f"--account={sa}", "--format=value(status)"]
    r = subprocess.run(
        [
            *gc,
            "compute",
            "instances",
            "list",
            f"--project={proj}",
            "--filter",
            f"name~'^feeder-fleet-{run}-'",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode == 0:
        sts = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
        gce_running = sum(1 for s in sts if s == "RUNNING")
        gce_terminated = sum(1 for s in sts if s == "TERMINATED")
slots=[]
for s in m.get("slots") or []:
    if s.get("state") == "probe_fail":
        continue
    row = {
        "slot": s.get("slot"),
        "state": s.get("state"),
        "ppm_complete": s.get("ppm_complete"),
        "port": s.get("port"),
        "batch": s.get("batch"),
    }
    if s.get("refresh_ppm") is not None:
        row["refresh_ppm"] = s.get("refresh_ppm")
    slots.append(row)
out={
    "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "agent": "fleet-cursor",
    "run_id": run,
    "vms": m.get("vms"),
    "vms_slots_assigned": m.get("vms"),
    "gce_running": gce_running,
    "gce_terminated": gce_terminated,
    "vms_note": "vms_slots_assigned=rows in slots.tsv (IPRoyal bindings); gce_running=instances billed",
    "complete_ppm_15m": m.get("complete_ppm"),
    "upvote_refresh_ppm_15m": m.get("upvote_refresh_ppm_15m"),
    "attempt_ppm_15m": m.get("attempt_ppm"),
    "pkg_md5": "uYYdW17hoPBJjpMGoR7lKw==",
    "staging": "raw/_pacetest/shared",
    "slots_summary": slots,
    "mailbox": "usersim_sim/mailbox/from_cursor/",
}
print(json.dumps(out, indent=2))
PY
