#!/usr/bin/env python3
"""Sample upvote refresh timing from repullupvotes slots (orchestrator telemetry)."""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROBE = r'''python3 << "PY"
import glob,json,re,statistics,socket
from datetime import datetime,timezone
host=socket.gethostname()
slot=re.search(r"-(\d+)$", host)
slot=int(slot.group(1)) if slot else -1
lf=sorted(glob.glob("/opt/ph/reuse/run_*.log"))[-1:]
log_name=lf[0].rsplit("/",1)[-1] if lf else None
lines=open(lf[0],errors="ignore").read().splitlines() if lf else []
pat=re.compile(r"^(\d{2}:\d{2}:\d{2}) \+(\d+)s upvotes endCursor chain (\d+) of (\d+) pages (\d+) ended (\S+)")
uv=[]
for i,l in enumerate(lines):
 m=pat.search(l)
 if m: uv.append({"plus_s":int(m.group(2)),"new":int(m.group(3)),"hdr":int(m.group(4)),"pages":int(m.group(5)),"ended":m.group(6),"t":m.group(1),"i":i})
def tosec(t):
 h,mn,s=map(int,t.split(":")); return h*3600+mn*60+s
gaps=[(tosec(b["t"])-tosec(a["t"]))%86400 for a,b in zip(uv,uv[1:])]
last=uv[-80:] if len(uv)>=80 else uv
# status jsonl: saves + blocks last 2h
now=datetime.now(timezone.utc)
saves=[]
blocks_1h=blocks_cf_1h=0
BLOCKEV=("stopped_on_block","block_soft_retry","block_port_rotate","browser_open_failed","cf_backoff")
try:
 for ln in open("/opt/ph/reuse/status_"+host+".jsonl").read().splitlines()[-5000:]:
  try:j=json.loads(ln)
  except:continue
  t=j.get("utc")
  if not t: continue
  try:ts=datetime.fromisoformat(t.replace("Z","+00:00"))
  except:continue
  age=(now-ts).total_seconds()
  if j.get("handle") and j.get("rc")==0 and age<=7200:
   saves.append({"handle":j["handle"],"utc":t,"method":j.get("method")})
  ev=j.get("event") or ""
  if age<=3600 and (ev in BLOCKEV or (ev=="supervisor_run_end" and j.get("rc")==3)):
   blocks_1h+=1
   if "cf" in ev.lower() or "block" in ev.lower() or "browser" in ev.lower():
    blocks_cf_1h+=1
except Exception as e:
 pass
# browser startup: first fingerprint line in log + count FINGERPRINT in last 2h window
browser_start_s=None
fp_re=re.compile(r"FINGERPRINT|browser_open")
fp_recent=0
for l in lines:
 if fp_re.search(l):
  if browser_start_s is None and "browser" in l.lower():
    m=re.search(r"\+(\d+)s",l)
    if m: browser_start_s=int(m.group(1))
  fp_recent+=1
# deliberate wait: grep sleep lines in log tail
sleep_lines=[l for l in lines[-300:] if re.search(r"sleep|backoff|wait|429|rate",l,re.I)]
# ended early on small pages?
one_page=sum(1 for u in last if u["pages"]<=2)
trail_stop=0
for u in last:
 pass
out={
 "slot":slot,"log":log_name,"n_refresh_lines":len(uv),
 "sample_n":len(last),
 "pages_median":statistics.median([u["pages"] for u in last]) if last else None,
 "pages_p90":sorted([u["pages"] for u in last])[int(len(last)*0.9)] if len(last)>1 else (last[0]["pages"] if last else None),
 "pages_le_2":one_page,
 "upvotes_read_s_median":statistics.median([u["plus_s"] for u in last]) if last else None,
 "inter_person_gap_s_median":statistics.median(gaps[-len(last):]) if gaps else None,
 "inter_person_gap_s_mean":round(statistics.mean(gaps[-len(last):]),1) if gaps else None,
 "ended_modes":{e:sum(1 for u in last if u["ended"]==e) for e in {u["ended"] for u in last}},
 "blocks_per_hour":blocks_1h,
 "cf_block_events_per_hour":blocks_cf_1h,
 "browser_start_s_once_at_boot":browser_start_s,
 "fingerprint_or_open_lines_in_log":fp_recent,
 "recent_saves_n":len(saves),
 "recent_save_gap_median_s":statistics.median([(datetime.fromisoformat(saves[i+1]["utc"].replace("Z","+00:00"))-datetime.fromisoformat(saves[i]["utc"].replace("Z","+00:00"))).total_seconds() for i in range(len(saves)-1)]) if len(saves)>2 else None,
 "last_12_uv":last[-12:],
}
print(json.dumps(out))
PY
'''


def probe_slot(slot: str, zone: str, proj: str, sa: str, run_id: str) -> dict:
    name = f"feeder-fleet-{run_id}-{slot}"
    try:
        r = subprocess.run(
            [
                "gcloud",
                "--account",
                sa,
                "compute",
                "ssh",
                name,
                f"--zone={zone}",
                f"--project={proj}",
                "--tunnel-through-iap",
                "--quiet",
                "--ssh-flag=-o ConnectTimeout=12",
                f"--command={PROBE}",
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        for ln in r.stdout.splitlines():
            if ln.startswith("{"):
                return json.loads(ln)
        return {"slot": int(slot), "error": (r.stderr or r.stdout)[-200:]}
    except Exception as e:
        return {"slot": int(slot), "error": str(e)[:200]}


def main() -> int:
    art = Path(os.environ.get("FLEET_ART", "results/ph_fleet_full/20261108t082000z"))
    run_id = os.environ.get("PACE_FLEET_RUN_ID", "20261108t082000z").lower()
    proj = os.environ["GCP_PROJECT"]
    sa = os.environ.get(
        "PACE_SERVICE_ACCOUNT", f"usersim-cloud-agent@{proj}.iam.gserviceaccount.com"
    )
    zone = subprocess.check_output(
        [
            "gcloud",
            "compute",
            "instances",
            "list",
            "--project",
            proj,
            "--filter",
            f"name=feeder-fleet-{run_id}-9",
            "--format=value(zone.basename())",
        ],
        text=True,
    ).strip()
    slots = (os.environ.get("FLEET_UPVOTE_SLOTS") or os.environ.get("UPVOTE_SLOTS") or "9 27 38").split()
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(lambda s: probe_slot(s, zone, proj, sa, run_id), slots))
    print(json.dumps({"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "slots": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())