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
attempt_c = float(m.get("attempt_ppm") or 0)
# ETA only from observed complete_ppm (orchestrator: do not assume 2/min while 0 observed).
eta = {
    "need_list_incomplete_store": inc,
    "need_list_new_in_queue": new,
    "need_list_work_remaining": need_left,
    "complete_ppm_15m_observed": ppm_c,
    "attempt_ppm_15m_observed": attempt_c,
}
if ppm_c >= 0.05 and need_left > 0:
    mins = need_left / ppm_c
    eta["eta_minutes_at_observed_ppm"] = round(mins, 1)
    eta["eta_utc_at_observed_ppm"] = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=mins)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    eta["eta_status"] = "from_observed"
else:
    eta["eta_status"] = "stalled_at_zero_complete_ppm"
    eta["eta_utc_at_observed_ppm"] = None
    eta["eta_note"] = (
        f"No ETA at 0 complete/min; backlog {need_left} until stacks/tab gate passes or slots recover."
    )
deadline = datetime.datetime(2026, 11, 21, 18, 0, tzinfo=datetime.timezone.utc)
eta["orchestrator_deadline_utc"] = deadline.strftime("%Y-%m-%dT%H:%M:%SZ")
mins_dl = (deadline - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 60
eta["minutes_to_deadline"] = round(mins_dl, 1)
if mins_dl > 0:
    eta["complete_ppm_required_for_deadline"] = round(need_left / mins_dl, 2)
out["need_list_eta"] = eta
rerun = float(m.get("rerun_ppm") or 0)
attempt = attempt_c
rr_files = "fix_need_list_20261121T1335Z.txt"
strat_path = (art.parent.parent.parent / "scripts/vm/ph_strategies/fleet_optimize.env").resolve()
if strat_path.is_file():
    for ln in strat_path.read_text().splitlines():
        if ln.startswith("PH_RR_FILES="):
            rr_files = ln.split("=", 1)[1].strip()
stale_n = sum(1 for s in m.get("slots") or [] if s.get("state") in ("stale", "dead") and int(s.get("age") or 0) > 1800)
dead_n = sum(1 for s in m.get("slots") or [] if s.get("state") == "dead")
cold_n = sum(1 for s in m.get("slots") or [] if s.get("state") in ("cold", "cf_wall"))
walls = int(sum(int(s.get("walls") or 0) for s in m.get("slots") or []))
win_c = sum(int(s.get("win_complete") or 0) for s in m.get("slots") or [])
win_r = sum(int(s.get("win_rerun") or 0) for s in m.get("slots") or [])
_refresh_ppm = float(m.get("upvote_refresh_ppm_15m") or 0)
_refresh_active = [
    int(s["slot"])
    for s in m.get("slots") or []
    if float(s.get("refresh_ppm") or 0) > 0.05
]
_refresh_dead = [
    int(s["slot"])
    for s in m.get("slots") or []
    if s.get("slot") in (9, 27, 38) and s.get("state") in ("dead", "cf_wall", "stale")
    and float(s.get("refresh_ppm") or 0) < 0.05
]
_excl = int(refill.get("refresh_priority_excluded") or 0)
out["upvote_refresh_diagnosis"] = {
    "refresh_slots": [9, 27, 38],
    "refresh_slots_active_ppm_gt_0": _refresh_active,
    "refresh_slots_down_15m": _refresh_dead,
    "pkg_md5_patch": "REPULL_REFRESH_PKG_MD5 on ph_batch repullupvotes (run.pkg_md5 from PKG_MD5)",
    "pkg_md5_patch_deployed_utc": "2026-11-21T16:32:00Z",
    "population_1721Z_pkg_md5_confirmed": True,
    "population_1721Z_staged_all_audited": 210,
    "held_legacy_pre_patch_approx": 122,
    "population_audit_1622Z_held_no_pkg_md5": 93,
    "upvote_refresh_ppm_15m": _refresh_ppm,
    "refresh_rate_drop_3h": {
        "approx_ppm_3h_ago": 8.1,
        "ppm_now": round(_refresh_ppm, 2),
        "why": [
            "slot38 dead ~since 21:15Z (was ~1–2 refresh/min)",
            "only slots 9+27 actively repullupvotes now (~half fleet refresh capacity)",
            f"{_excl} handles in refresh_priority_excluded (need-list-first queue steals pdeep slots)",
            f"dead/cf/stale historical slots: {dead_n} dead, {cold_n} cold/cf_wall (no pdeep completes either)",
            "population 2221Z: many refresh FAIL_partial from upvotes paging budget on 9/27 (staged but items_added=0)",
        ],
    },
    "note": "New refresh uploads merge (1721Z). ~122 older staged HELD until those handles refresh again.",
}
tfc = {}
tfp = art / "tab_failure_counts.json"
if tfp.is_file():
    try:
        tfc = json.load(open(tfp))
    except Exception:
        tfc = {}
out["need_list_tab_failure_counts"] = tfc.get("need_list_tab_failure_people_counts") or {}
_rer = {}
_rerp = art / "refresh_end_reasons.json"
if _rerp.is_file():
    try:
        _rer = json.load(open(_rerp))
    except Exception:
        _rer = {}
out["upvote_refresh_end_measured_60m"] = (_rer.get("upvote_refresh_end_measured_60m") or _rer.get("need_list_refresh_end_measured_60m") or {})
out["upvote_refresh_end_per_slot"] = _rer.get("per_slot") or []
out["need_list_stacks_fail_measured_60m"] = tfc.get("need_list_stacks_fail_measured_60m") or {}
out["stacks_store_assumption"] = tfc.get("stacks_store_assumption") or {}
out["need_list_attempt_ppm_15m"] = m.get("attempt_ppm")
out["need_list_tab_failure_meta"] = {k: tfc.get(k) for k in (
    "utc", "audits_scanned", "need_list_incomplete_store", "orchestrator_deadline_22z_tab_counts_utc",
    "forecast_deadline_00_05_pt_utc", "note",
) if k in tfc}
forecast_dl = datetime.datetime(2026, 11, 22, 8, 5, tzinfo=datetime.timezone.utc)
_stacks_est = int((tfc.get("stacks_store_assumption") or {}).get("need_list_incomplete_store") or inc)
_stacks_hr = {}
_shp = art / "stacks_pull_hour.json"
if _shp.is_file():
    try:
        _stacks_hr = json.load(open(_shp))
    except Exception:
        _stacks_hr = {}
_measured = _stacks_hr.get("need_list_stacks_fail_measured_60m") or {}
_pqnf = int(_measured.get("ProfileStacksPage_PersistedQueryNotFound_log_lines") or 0)
_reads_ok = ppm_c >= 0.05 and win_c > 0
if _reads_ok:
    _blocker = None
elif _pqnf > 0:
    _blocker = "ProfileStacksPage GQL PersistedQueryNotFound"
else:
    _blocker = (
        "stacks coverage got=0 on pulls (hash bfdb9f43 on GCS; "
        f"60m measured stacks_fail/{_measured.get('pdeep_attempt_handles_sum_slots','?')} attempts; "
        "CF/dead-slot restarts not PQNF)"
    )
out["stacks_tab_reads_ok"] = _reads_ok
out["stacks_tab_status"] = {
    "reads_ok": _reads_ok,
    "blocker": _blocker,
    "pgql_hash_bfdb9f43_on_gcs": True,
    "pqnf_log_lines_60m": _pqnf,
    "need_list_incomplete_blocked_est": 0 if _reads_ok else _stacks_est,
    "forecast_deadline_00_05_pt_utc": forecast_dl.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "note": "Orchestrator 21:08Z: reads_ok true when need-list whole() saves resume (complete_ppm>0, win_complete>0).",
}
out["standing_information_needs"] = {
    "launch_day_social_graph": {
        "orc_request_utc": "2026-11-22T04:25:00Z",
        "lineup_at_pt": "00:01",
        "deadline_pt": "02:00 same PT day",
        "scope_per_launch": "all makers + hunter",
        "whole_person_tabs": ["followers", "following", "upvotes"],
        "stamp": "read time on each pull (standard run timing)",
        "priority": "ahead of need-list backlog",
        "need_list": "still wanted",
        "fleet_note": (
            "Acknowledged. Today: maker_header SSR (ph_maker_headers) only; "
            "full people queue from daily lineup not yet in refill. Same Stacks PQNF blocks wholes until uYYdW17 hash fixed."
        ),
        "nov22_pt_deadline_utc": "2026-11-22T10:00:00Z",
    },
}
out["need_list_diagnosis"] = {
    "why_not_need_list_new_completes": (
        "need_list.jsonl still skipped under PH_FLEET_RR_ONLY; queue is PH_RR_FILES. "
        "Repointed to need-list-first file but dead/stale slots + stacks tab failure => 0 complete/min."
    ),
    "strategy": {
        "ph_fleet_rr_only": True,
        "ph_rr_files": rr_files,
        "refill_pdeep_new_queued": new,
        "refill_pdeep_incomplete_queued": inc,
    },
    "fleet_15m_window": {
        "win_complete_persons": win_c,
        "win_rerun_persons": win_r,
        "rerun_fraction_of_attempts": round(rerun / attempt, 3) if attempt > 0 else None,
        "stale_or_dead_slots_gt_30m": stale_n,
        "dead_slots": dead_n,
        "cold_or_cf_slots": cold_n,
        "cf_wall_events_15m": walls,
    },
    "failing_tab_counts_15m_window": {
        "ProfileStacksPage_persisted_query_not_found": "observed on pdeep pulls (blocks whole())",
        "population_fail_partial_1622Z": {
            "not_filled_comment_times": 10,
            "stacks_hunted_forums_following_followers_collections_activity": 3,
        },
    },
    "tab_failures_observed": {
        "ProfileStacksPage": "gql PersistedQueryNotFound → stacks 0 (blocks whole() / header_pct)",
        "ProfileForumsPage": "paginates OK",
        "ProfileActivityPage": "paginates OK",
        "ProfileHuntedPage": "paginates OK",
        "cf_wall_slots_15m": [s.get("slot") for s in m.get("slots") or [] if int(s.get("walls") or 0) > 0],
    },
    "deadline_note_18z_today": (
        f"At measured complete_ppm={ppm_c:.3f} need_list ETA misses 18:00Z; "
        f"need ~{eta.get('complete_ppm_required_for_deadline', '?')} complete/min."
    ),
}
print(json.dumps(out, indent=2))
PY
