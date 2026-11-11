#!/usr/bin/env python3
"""Build Population audit handoff text (no VM changes)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_cov_issues(obj: dict) -> list[str]:
    issues: list[str] = []
    run = obj.get("run") or {}
    if run.get("comment_times_missing"):
        issues.append("comment_times")
    cov = (obj.get("coverage") or {}) if isinstance(obj.get("coverage"), dict) else {}
    # coverage may be in run audit — check tabs in res structure
    tabs = obj.get("tabs") or {}
    for name, tab in tabs.items():
        if not isinstance(tab, dict):
            continue
        st = tab.get("status") or ""
        if st == "partial":
            issues.append(f"tab_partial:{name}")
        if st == "lists_only":
            issues.append(f"lists_only:{name}")
    hdr = obj.get("header") or {}
    if isinstance(hdr, dict) and hdr.get("followers_count") and hdr.get("followers"):
            fc, got = hdr["followers_count"], len(hdr.get("followers") or [])
            if got < 0.98 * fc:
                issues.append("followers_short")
    return issues


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    art = Path(os.environ.get("FLEET_ART", root / "results/ph_fleet_full/20261108t082000z"))
    run_id = os.environ.get("PACE_FLEET_RUN_ID", "20261108t082000z").lower()
    vm_root = os.environ["PACE_GCS_VM_ROOT"]
    bucket = os.environ.get("MVP_GCS_BUCKET", "")
    pkg = os.environ.get("FLEET_PKG", "bsit_full17.tgz")
    pkg_md5 = os.environ.get("FLEET_PKG_MD5", "Ku9PrVAfo8f+uDrIVfW8Bg==")
    overlays = (
        "patch_require_full_save, patch_lazy_tabs, patch_same_port_retry, "
        "patch_soft_open_rotate, fleet_optimize.env PH_REQUIRE_FULL_SAVE=1"
    )
    # Recent saves sample for handoff (Population full-audits all objects)
    sample: list[dict] = []
    try:
        r = subprocess.run(
            ["gcloud", "storage", "ls", "-l", f"{vm_root}/*.json"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        lines = [ln for ln in r.stdout.splitlines() if ln.strip().endswith(".json")]
        # take last 40 by listing order (approx recent)
        for ln in lines[-40:]:
            parts = ln.split()
            if len(parts) < 4:
                continue
            uri = parts[-1]
            handle = Path(uri).name.replace(".json", "")
            sample.append({"handle": handle, "uri": uri, "size_bytes": int(parts[0]) if parts[0].isdigit() else None})
    except Exception as e:
        sample = [{"error": str(e)[:200]}]

    # Optional deep read on up to 8 recent handles
    details: list[dict] = []
    for row in sample[-8:]:
        uri = row.get("uri")
        if not uri:
            continue
        try:
            raw = subprocess.run(
                ["gcloud", "storage", "cat", uri],
                capture_output=True,
                text=True,
                timeout=45,
            )
            if raw.returncode != 0:
                details.append({"handle": row["handle"], "read_error": raw.stderr[:120]})
                continue
            obj = json.loads(raw.stdout)
            issues = _load_cov_issues(obj)
            details.append(
                {
                    "handle": row["handle"],
                    "issues": issues or ["needs_population_audit"],
                    "truncated_budget": bool(obj.get("truncated_budget")),
                }
            )
        except Exception as e:
            details.append({"handle": row.get("handle"), "read_error": str(e)[:120]})

    packet = {
        "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": run_id,
        "output_people_gcs_prefix": f"{vm_root}/",
        "output_logs_gcs_prefix": f"{vm_root}/logs/",
        "output_status_gcs_prefix": f"{vm_root}/status/",
        "collector_pkg": pkg,
        "collector_pkg_md5": pkg_md5,
        "collector_overlays": overlays,
        "budget_constraints": {
            "weekly_paid_data_stop_bytes": 195e9,
            "weekly_paid_data_stop_usd": 200,
            "gcp_daily_ceiling_usd": 100,
            "note": "No new VMs/IAM/IP rotation authorized on this thread",
        },
        "fleet_honest_status": {
            "zero_incomplete_not_verified": True,
            "upload_gate": "PH_REQUIRE_FULL_SAVE blocks gs:// upload when coverage fails",
            "lists_only_never_complete": True,
        },
        "manifest_note": f"~{len(sample)} recent handles sampled; Population must audit every object under prefix",
        "sample_handles": sample,
        "sample_issue_hints": details,
        "mvp_bucket": bucket,
    }
    out = art / "population_audit_packet.json"
    out.write_text(json.dumps(packet, indent=2))
    # Compact message for Pub/Sub size limits
    msg = (
        f"AUDIT_HANDOFF run={run_id} prefix={vm_root}/ pkg={pkg} md5={pkg_md5} "
        f"overlays={overlays} ZERO_COMPLETE_UNVERIFIED=true. "
        f"Reply to=fleet-cursor with repair_list JSON. Sample_issues={json.dumps(details)[:2500]}"
    )
    (art / "population_audit_message.txt").write_text(msg)
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
