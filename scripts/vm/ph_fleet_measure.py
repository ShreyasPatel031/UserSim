#!/usr/bin/env python3
"""Parallel fleet health sample: realized ppm, active/stale/cold per slot."""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def fleet_live_hb_age_sec() -> int | None:
    bucket = os.environ.get("MVP_GCS_BUCKET")
    if not bucket:
        return None
    try:
        r = subprocess.run(
            [
                "gcloud",
                "storage",
                "cat",
                f"gs://{bucket}/usersim_sim/raw/ph_at_launch/live/state/fleet_capture.hb",
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        line = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
        m = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", line)
        if not m:
            return None
        t = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - t).total_seconds())
    except Exception:
        return None

ZONE = os.environ["PACE_ZONE"]
PROJ = os.environ["GCP_PROJECT"]
RUN_ID = os.environ.get("PACE_FLEET_RUN_ID", "").lower()
SA = os.environ.get("PACE_SERVICE_ACCOUNT", f"usersim-cloud-agent@{PROJ}.iam.gserviceaccount.com")
ART = Path(os.environ.get("FLEET_ART", f"results/ph_fleet_full/{RUN_ID}"))

WINDOW_MIN = float(os.environ.get("FLEET_WINDOW_MIN", "15"))

# State and rate come from this VM's status rows in the last WINDOW_MIN minutes (not since first_pull):
#   complete = rc 0 saved person (pdeep pfull_* rows passed the whole() gate; legacy rows need header_pct >= 98)
#   rerun    = any other person outcome (not_whole rc 2, errors, incomplete_skip_upload)
#   active   = a person row in the last 10 min; cf_wall = only block/CF rows in the window; idle = neither
PROBE = r'''python3 -c "
import json, subprocess, socket
from datetime import datetime, timezone
W=__WINDOW__*60
now=datetime.now(timezone.utc).timestamp()
host=socket.gethostname()
def ts(u):
  try: return datetime.fromisoformat(u.replace('Z','+00:00')).timestamp()
  except Exception: return None
nc=nr=nc_all=nr_all=0; last_person=None; walls=0; port=None
BLOCKEV=('browser_open_failed','stopped_on_block','block_port_rotate','block_soft_retry','block_new_port')
try: rows=open('/opt/ph/reuse/status_'+host+'.jsonl').read().splitlines()
except Exception: rows=[]
for ln in rows:
  try: j=json.loads(ln)
  except Exception: continue
  t=ts(j.get('utc') or '')
  if j.get('port'): port=j.get('port')
  ev=j.get('event'); rc=j.get('rc')
  if j.get('handle') and (rc is not None or ev=='incomplete_skip_upload'):
    ok = rc==0 and ev!='incomplete_skip_upload' and (str(j.get('method') or '').startswith('pfull') or float(j.get('header_pct') or 0)>=98)
    if ok: nc_all+=1
    else: nr_all+=1
    if t and now-t<=W:
      if ok: nc+=1
      else: nr+=1
    if t: last_person=max(last_person or 0,t)
  elif (ev in BLOCKEV or (ev=='supervisor_run_end' and rc==3)) and t and now-t<=W:
    walls+=1
batch=subprocess.call(['pgrep','-f','[p]h_batch.py|[p]deep.py'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)==0
refresh_win=0
if batch:
  try:
    import glob,re
    from datetime import datetime as _dt, timedelta as _td
    logs=sorted(glob.glob('/opt/ph/reuse/run_*.log'))
    if logs:
      lf=logs[-1]
      bm=re.match(r'run_(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})Z', lf.rsplit('/',1)[-1])
      base=_dt(int(bm.group(1)),int(bm.group(2)),int(bm.group(3)),int(bm.group(4)),int(bm.group(5)),tzinfo=timezone.utc) if bm else None
      for ln in open(lf, errors='ignore'):
        if 'upvotes endCursor' not in ln: continue
        ps=ln.split()
        if len(ps)<2 or ':' not in ps[0]: continue
        if not base: refresh_win+=1; continue
        h,mn,s=map(int,ps[0].split(':'))
        nd=_dt.now(timezone.utc)
        t=nd.replace(hour=h,minute=mn,second=s,microsecond=0).timestamp()
        age=now-t
        if age<0 or age>W:
          t=(nd-_td(days=1)).replace(hour=h,minute=mn,second=s,microsecond=0).timestamp()
          age=now-t
        if 0<=age<=W: refresh_win+=1
  except Exception: pass
m=W/60.0
refresh_ppm=round(refresh_win/m,4) if refresh_win else 0.0
age=int(now-last_person) if last_person else -1
if last_person and now-last_person<=300: state='active'
elif not batch: state='dead'
elif last_person and now-last_person<=600: state='active'
elif walls: state='cf_wall'
elif last_person: state='stale'
else: state='cold'
print(json.dumps({'n':nc_all+nr_all,'n_complete':nc_all,'n_rerun':nr_all,'win_complete':nc,'win_rerun':nr,'walls':walls,'age':age,'ppm':round(nc/m,4),'ppm_complete':round(nc/m,4),'ppm_attempt':round((nc+nr)/m,4),'ppm_rerun':round(nr/m,4),'refresh_ppm':refresh_ppm,'refresh_win':refresh_win,'state':state,'batch':batch,'port':port}))
"'''.replace("__WINDOW__", str(WINDOW_MIN))


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

    upvote_slots = set(
        (os.environ.get("FLEET_UPVOTE_SLOTS") or os.environ.get("UPVOTE_SLOTS") or "9 27 38").split()
    )
    live_slots = set((os.environ.get("FLEET_LIVE_SLOTS") or "39").split())
    live_hb_max = int(os.environ.get("FLEET_LIVE_HB_MAX_SEC", "1200"))
    live_hb_age = fleet_live_hb_age_sec()
    refresh_ppm_total = 0.0
    for r in rows:
        slot = str(r.get("slot"))
        rp = float(r.get("refresh_ppm") or 0)
        if slot in upvote_slots:
            refresh_ppm_total += rp
            if rp >= 0.15 and r.get("batch") and r.get("state") in ("dead", "stale", "cold"):
                r["state"] = "active_upvote"
        if slot in live_slots and live_hb_age is not None and live_hb_age <= live_hb_max:
            r["state"] = "active_live"
            r["batch"] = True
            r["age"] = live_hb_age
            r["live_capture_primary"] = True

    now = datetime.now(timezone.utc)
    realized = sum((r.get("ppm_complete") or 0) for r in rows)
    attempt_ppm = sum((r.get("ppm_attempt") or 0) for r in rows)
    rerun_ppm = sum((r.get("ppm_rerun") or 0) for r in rows)
    active = [r for r in rows if r.get("state") in ("active", "active_upvote", "active_live")]
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
        "metric_note": f"complete_ppm=complete saved people in last {WINDOW_MIN:g} min / {WINDOW_MIN:g}; incomplete pulls count as rerun only",
        "upvote_refresh_ppm_15m": round(refresh_ppm_total, 3),
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
    try:
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "ph_fleet_progress_history.py")],
            check=False,
            timeout=30,
            env={**os.environ, "PACE_FLEET_RUN_ID": RUN_ID},
        )
    except Exception:
        pass
    bucket = os.environ.get("MVP_GCS_BUCKET", "")
    if bucket:
        gcs_key = "usersim_sim/ops/fleet/dashboard_live.json"
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
