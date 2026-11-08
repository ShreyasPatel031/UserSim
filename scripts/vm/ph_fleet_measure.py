#!/usr/bin/env python3
"""Parallel fleet health sample: realized ppm, active/stale/cold per slot."""
from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ZONE = os.environ["PACE_ZONE"]
PROJ = os.environ["GCP_PROJECT"]
RUN_ID = os.environ.get("PACE_FLEET_RUN_ID", "").lower()
SA = os.environ.get("PACE_SERVICE_ACCOUNT", f"usersim-cloud-agent@{PROJ}.iam.gserviceaccount.com")
ART = Path(os.environ.get("FLEET_ART", f"results/ph_fleet_full/{RUN_ID}"))

PROBE = r'''python3 -c "
import json, subprocess, glob
from pathlib import Path
from datetime import datetime, timezone
now=datetime.now(timezone.utc)
out=Path('/opt/ph/reuse/out')
files=[p for p in out.glob('*.json') if p.name!='hb.json'] if out.exists() else []
n_attempt=len(files)
newest=max((p.stat().st_mtime for p in files), default=0)
age=int((now.timestamp()-newest)) if newest else -1
fp=idr=None
p=Path('/opt/ph/reuse/setup_timing.jsonl')
for ln in (p.read_text().splitlines() if p.exists() else []):
  try: j=json.loads(ln)
  except: continue
  if j.get('event')=='first_pull': fp=j.get('utc')
  if j.get('event')=='identity_ready': idr=j.get('utc')
import socket
host=socket.gethostname()
status_files=[sp for sp in glob.glob('/opt/ph/reuse/status*.jsonl') if host in sp]
if not status_files:
  status_files=[sp for sp in glob.glob('/opt/ph/reuse/status_feeder-fleet*.jsonl')]
n_upload=n_complete=n_rerun=0
for sp in status_files:
  for ln in open(sp):
    try: j=json.loads(ln)
    except: continue
    if not j.get('handle'): continue
    if j.get('event')=='incomplete_skip_upload':
      n_rerun+=1; continue
    rc=j.get('rc')
    if rc==0:
      n_upload+=1
      hp=float(j.get('header_pct') or 0)
      if hp>=98: n_complete+=1
      else: n_rerun+=1
    elif rc not in (None,):
      n_rerun+=1
batch=subprocess.call(['pgrep','-f','ph_batch.py'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)==0
ppm_attempt=ppm_complete=ppm_rerun=0.0
if fp:
  t=datetime.fromisoformat(fp.replace('Z','+00:00'))
  sec=max(60.0,(now-t).total_seconds())
  n_try=n_complete+n_rerun
  ppm_attempt=round(n_try*60.0/sec,4)
  ppm_complete=round(n_complete*60.0/sec,4)
  ppm_rerun=round(n_rerun*60.0/sec,4)
state='cold'
if not batch: state='dead'
elif not fp: state='cf_wall'
elif age>=0 and age<300: state='active'
elif fp: state='stale'
print(json.dumps({'n':n_attempt,'n_complete':n_complete,'n_rerun':n_rerun,'n_upload':n_upload,'age':age,'ppm':ppm_complete,'ppm_attempt':ppm_attempt,'ppm_complete':ppm_complete,'ppm_rerun':ppm_rerun,'state':state,'fp':fp,'idr':idr,'batch':batch}))
"'''


def probe_slot(slot: str) -> dict:
    name = f"feeder-fleet-{RUN_ID}-{slot}"
    try:
        r = subprocess.run(
            [
                "gcloud",
                "--account",
                SA,
                "compute",
                "ssh",
                name,
                f"--zone={ZONE}",
                f"--project={PROJ}",
                "--tunnel-through-iap",
                "--quiet",
                "--ssh-flag=-o ConnectTimeout=8",
                "--ssh-flag=-o StrictHostKeyChecking=no",
                f"--command={PROBE}",
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        for ln in r.stdout.splitlines():
            if ln.startswith("{"):
                d = json.loads(ln)
                d["slot"] = int(slot)
                return d
    except Exception as e:
        return {"slot": int(slot), "state": "probe_fail", "err": str(e)[:120]}
    return {"slot": int(slot), "state": "probe_fail"}


def main() -> int:
    slots = [
        ln.split("\t")[0]
        for ln in ART.joinpath("slots.tsv").read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    rows: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        rows = list(ex.map(probe_slot, slots))

    now = datetime.now(timezone.utc)
    realized = sum(
        (r.get("ppm_complete") or r.get("ppm") or 0)
        for r in rows
        if r.get("state") in ("active", "stale")
    )
    attempt_ppm = sum(
        (r.get("ppm_attempt") or r.get("ppm") or 0)
        for r in rows
        if r.get("state") in ("active", "stale")
    )
    rerun_ppm = sum(
        (r.get("ppm_rerun") or 0) for r in rows if r.get("state") in ("active", "stale")
    )
    active = [r for r in rows if r.get("state") == "active"]
    stale = [r for r in rows if r.get("state") == "stale"]
    cold = [r for r in rows if r.get("state") in ("cold", "cf_wall", "dead")]
    productive = active + [r for r in stale if (r.get("ppm") or 0) >= 0.15]

    snap = {
        "utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": RUN_ID,
        "vms": len(slots),
        "realized_ppm": round(realized, 3),
        "complete_ppm": round(realized, 3),
        "attempt_ppm": round(attempt_ppm, 3),
        "rerun_ppm": round(rerun_ppm, 3),
        "metric_note": "complete_ppm=status rc0+header>=98; incomplete pulls count as rerun only",
        "active_vms": len(active),
        "stale_vms": len(stale),
        "cold_vms": len(cold),
        "productive_vms": len(productive),
        "avg_ppm_productive": round(
            sum((r.get("ppm_complete") or r.get("ppm") or 0) for r in productive)
            / len(productive),
            4,
        )
        if productive
        else 0,
        "vms_needed_for_20": int(
            (
                20
                / (
                    sum((r.get("ppm_complete") or r.get("ppm") or 0) for r in productive)
                    / len(productive)
                )
            )
            if productive
            and sum((r.get("ppm_complete") or r.get("ppm") or 0) for r in productive) > 0
            else 30
        ),
        "slots": rows,
        "target_lo": float(os.environ.get("FLEET_TARGET_LO", "20")),
        "target_hi": float(os.environ.get("FLEET_TARGET_HI", "30")),
    }
    ART.mkdir(parents=True, exist_ok=True)
    Path(ART / "fleet_measure.json").write_text(json.dumps(snap, indent=2))
    dash = (
        json.loads((ART / "dashboard_snapshot.json").read_text())
        if (ART / "dashboard_snapshot.json").exists()
        else {}
    )
    dash.update(
        {
            "utc": snap["utc"],
            "vms": snap["vms"],
            "fleet_ppm": snap["complete_ppm"],
            "realized_ppm": snap["complete_ppm"],
            "complete_ppm": snap["complete_ppm"],
            "attempt_ppm": snap["attempt_ppm"],
            "rerun_ppm": snap["rerun_ppm"],
            "active_vms": snap["active_vms"],
            "stale_vms": snap["stale_vms"],
            "cold_vms": snap["cold_vms"],
            "productive_vms": snap["productive_vms"],
            "vms_needed_for_20": snap["vms_needed_for_20"],
            "avg_ppm_productive": snap["avg_ppm_productive"],
            "json_sum_fleet": sum(r.get("n", 0) for r in rows),
        }
    )
    (ART / "dashboard_snapshot.json").write_text(json.dumps(dash, indent=2))
    live = {**snap, "dashboard": dash}
    live_path = ART / "dashboard_live.json"
    live_path.write_text(json.dumps(live, indent=2))

    root = Path(__file__).resolve().parents[2]
    web = root / "fleet-dashboard"
    web.mkdir(parents=True, exist_ok=True)
    (web / "snapshot.json").write_text(json.dumps(live, indent=2))
    bucket = os.environ.get("MVP_GCS_BUCKET", "")
    if bucket:
        gcs_key = "usersim_sim/raw/ph_population/people_live/vm/dashboard_live.json"
        gcs_uri = f"gs://{bucket}/{gcs_key}"
        try:
            subprocess.run(
                ["gcloud", "storage", "cp", "-q", str(live_path), gcs_uri],
                check=False,
                timeout=120,
            )
            public = f"https://storage.googleapis.com/{bucket}/{gcs_key}"
            (web / "config.js").write_text(
                f"window.FLEET_SNAPSHOT_URL = {json.dumps(public)};\n"
            )
        except Exception:
            (web / "config.js").write_text("window.FLEET_SNAPSHOT_URL = '';\n")
    print(json.dumps(snap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
