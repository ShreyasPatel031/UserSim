#!/usr/bin/env python3
"""Progress on refresh_priority_<day> drain (upvote slots 9/27/38)."""
from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _ts(u: str) -> float | None:
    try:
        return datetime.fromisoformat(u.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _ssh_status(slot: str, run_id: str, proj: str, zone: str, sa: str) -> list[dict]:
    name = f"feeder-fleet-{run_id}-{slot}"
    dest = Path(f"/tmp/upvote_st_{slot}.jsonl")
    r = subprocess.run(
        [
            "gcloud",
            "--account",
            sa,
            "compute",
            "scp",
            f"{name}:/opt/ph/reuse/status_{name}.jsonl",
            str(dest),
            f"--zone={zone}",
            f"--project={proj}",
            "--tunnel-through-iap",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 0 or not dest.exists():
        return []
    rows: list[dict] = []
    for ln in dest.read_text().splitlines():
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    return rows


def _is_refresh_row(j: dict) -> bool:
    if j.get("rc") != 0:
        return False
    if not j.get("handle"):
        return False
    method = str(j.get("method") or "")
    if method.startswith("pfull"):
        return False
    cov = j.get("coverage") or {}
    up = cov.get("upvotes")
    if up is None:
        return False
    return True


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    art = Path(os.environ.get("FLEET_ART", root / "results/ph_fleet_full/20261108t082000z"))
    state_path = art / "upvote_refresh_priority.state.json"
    if not state_path.exists():
        print(json.dumps({"error": "no state; run ph_fleet_apply_refresh_priority.sh"}))
        return 1
    state = json.loads(state_path.read_text())
    proj = os.environ["GCP_PROJECT"]
    zone = os.environ["PACE_ZONE"]
    run_id = os.environ.get("PACE_FLEET_RUN_ID", "20261108t082000z").lower()
    sa = f"usersim-cloud-agent@{proj}.iam.gserviceaccount.com"
    bucket = os.environ["MVP_GCS_BUCKET"]
    first_day = state["first_priority_day"]
    first_gcs = state["first_priority_gcs"].split(f"gs://{bucket}/", 1)[-1]
    tmp = Path("/tmp/rp_prog")
    tmp.mkdir(exist_ok=True)
    subprocess.run(
        ["gcloud", "storage", "cp", f"gs://{bucket}/{first_gcs}", str(tmp / "first.txt")],
        check=True,
        capture_output=True,
    )
    priority: set[str] = set()
    for ln in (tmp / "first.txt").read_text().splitlines():
        if not ln.strip() or ln.startswith("#"):
            continue
        h = ln.split()[0].lower().lstrip("@")
        if h:
            priority.add(h)
    t0 = _ts(state["deployed_utc"]) or 0.0
    slots = state.get("upvote_slots") or ["9", "27", "38"]
    done: set[str] = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        all_rows = list(ex.map(lambda s: _ssh_status(s, run_id, proj, zone, sa), slots))
    for rows in all_rows:
        for j in rows:
            t = _ts(j.get("utc") or "")
            if t is None or t < t0 - 60:
                continue
            h = (j.get("handle") or "").lower().lstrip("@")
            if h in priority and _is_refresh_row(j):
                done.add(h)
    n = len(priority)
    d = len(done)
    report = {
        "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "first_priority_day": first_day,
        "priority_n": n,
        "done_n": d,
        "done_pct": round(100.0 * d / n, 2) if n else None,
        "complete": d >= n and n > 0,
        "deployed_utc": state["deployed_utc"],
        "merged_gcs": state.get("merged_gcs"),
    }
    print(json.dumps(report, indent=2))
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    sys.exit(main())