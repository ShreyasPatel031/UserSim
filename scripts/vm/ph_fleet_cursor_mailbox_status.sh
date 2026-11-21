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
from pathlib import Path
art = Path(sys.argv[1]).resolve().parent
refill = {}
rp = art / "refill_state.json"
if rp.is_file():
    try:
        refill = json.load(open(rp))
    except Exception:
        refill = {}
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
inc = int(refill.get("pdeep_incomplete") or 0)
new = int(refill.get("pdeep_new") or 0)
need_left = inc + new
ppm_c = float(m.get("complete_ppm") or 0)
# Planning rate when recovering hung pdeep slots (orchestrator need-list ETA).
plan_ppm = ppm_c if ppm_c >= 0.15 else 2.0
eta = {
    "need_list_incomplete_store": inc,
    "need_list_new_in_queue": new,
    "need_list_work_remaining": need_left,
    "complete_ppm_15m_observed": ppm_c,
    "complete_ppm_planning_assumption": plan_ppm,
}
if plan_ppm > 0 and need_left > 0:
    mins = need_left / plan_ppm
    eta["eta_minutes_at_plan_ppm"] = round(mins, 1)
    eta["eta_utc_at_plan_ppm"] = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=mins)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
deadline = datetime.datetime(2026, 11, 21, 18, 0, tzinfo=datetime.timezone.utc)
eta["orchestrator_deadline_utc"] = deadline.strftime("%Y-%m-%dT%H:%M:%SZ")
if plan_ppm > 0:
    eta["minutes_to_deadline"] = round((deadline - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 60, 1)
    eta["complete_ppm_required_for_deadline"] = round(need_left / max(1, eta["minutes_to_deadline"]), 2)
out["need_list_eta"] = eta
rerun = float(m.get("rerun_ppm") or 0)
attempt = float(m.get("attempt_ppm") or 0)
stale_n = sum(1 for s in m.get("slots") or [] if s.get("state") in ("stale", "dead") and int(s.get("age") or 0) > 1800)
cold_n = sum(1 for s in m.get("slots") or [] if s.get("state") in ("cold", "cf_wall"))
walls = int(sum(int(s.get("walls") or 0) for s in m.get("slots") or []))
win_c = sum(int(s.get("win_complete") or 0) for s in m.get("slots") or [])
win_r = sum(int(s.get("win_rerun") or 0) for s in m.get("slots") or [])
out["need_list_diagnosis"] = {
    "why_not_need_list_new_completes": (
        "PH_FLEET_RR_ONLY=1 skips need_list.jsonl; pdeep pulls PH_RR_FILES "
        "(completion_queue fix list) only — re-pulls incomplete rows, not need_list first-time completes."
    ),
    "strategy": {
        "ph_fleet_rr_only": True,
        "ph_rr_files": "fix_completion_queue_20261118T0636Z.txt (completion_queue drain policy)",
        "refill_pdeep_new_queued": new,
        "refill_pdeep_incomplete_queued": inc,
    },
    "fleet_15m_window": {
        "win_complete_persons": win_c,
        "win_rerun_persons": win_r,
        "rerun_fraction_of_attempts": round(rerun / attempt, 3) if attempt > 0 else None,
        "stale_or_dead_slots_gt_30m": stale_n,
        "cold_or_cf_slots": cold_n,
        "cf_wall_events_15m": walls,
    },
    "tab_failures_observed": (
        "Primary blocker on active pulls: ProfileStacksPage gql PersistedQueryNotFound "
        "(stacks 0); Forums/Activity/Hunted paginate. Slot34 high cf_wall count."
    ),
    "deadline_note_18z_today": (
        f"At measured complete_ppm={ppm_c:.3f} need_list ETA misses 18:00Z; "
        f"need ~{eta.get('complete_ppm_required_for_deadline', '?')} complete/min."
    ),
}
print(json.dumps(out, indent=2))
PY
