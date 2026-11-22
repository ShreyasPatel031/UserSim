#!/usr/bin/env python3
"""Count repullupvotes end reasons from fleet VM logs + status (last hour)."""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROBE = r'''python3 << "PY"
import glob,json,re,socket
from collections import Counter
from datetime import datetime,timezone
host=socket.gethostname()
slot=int(re.search(r"-(\d+)$", host).group(1))
lines=[]
for lf in sorted(glob.glob("/opt/ph/reuse/run_*.log"))[-2:]:
    lines.extend(open(lf,errors="ignore").read().splitlines())
pat=re.compile(r"upvotes endCursor chain (\d+) of (\d+) pages (\d+) ended (\S+)")
log_ended=Counter()
log_pages_budget=Counter()
for l in lines[-12000:]:
    m=pat.search(l)
    if not m: continue
    ended=m.group(4)
    pages=int(m.group(3))
    log_ended[ended]+=1
    if ended=="budget":
        log_pages_budget[pages]+=1
# status: repull saves with paging.ended in uploaded JSON is not in status — use method+notes
st_ended=Counter()
st_budget=0
st_held=0
st_ph_end=0
now=datetime.now(timezone.utc)
try:
    for ln in open("/opt/ph/reuse/status_"+host+".jsonl"):
        try:j=json.loads(ln)
        except: continue
        if j.get("method")!="repullupvotes" or j.get("rc")!=0: continue
        t=j.get("utc")
        if not t: continue
        ts=datetime.fromisoformat(t.replace("Z","+00:00"))
        if (now-ts).total_seconds()>3600: continue
        cov=j.get("coverage") or {}
        uv=cov.get("upvotes") or {}
        if isinstance(uv,dict):
            pg=uv.get("paging") or {}
            end=pg.get("ended")
            if end: st_ended[end]+=1
except Exception as e:
    pass
print(json.dumps({"slot":slot,"log_ended_modes_2logs":dict(log_ended),"log_budget_by_pages":dict(log_pages_budget),
    "status_repull_60m_ended":dict(st_ended)}))
PY
'''


def probe(slot: str, zone: str, proj: str, sa: str, run_id: str) -> dict:
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
    root = Path(__file__).resolve().parents[2]
    run_id = os.environ.get("PACE_FLEET_RUN_ID", "20261108t082000z").lower()
    art = Path(os.environ.get("FLEET_ART", root / f"results/ph_fleet_full/{run_id}"))
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
    slots = (os.environ.get("FLEET_UPVOTE_SLOTS") or "9 27").split()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        rows = list(ex.map(lambda s: probe(s, zone, proj, sa, run_id), slots))
    log_all: Counter[str] = Counter()
    budget_pages: Counter[int] = Counter()
    for r in rows:
        for k, v in (r.get("log_ended_modes_2logs") or {}).items():
            log_all[k] += int(v)
        for k, v in (r.get("log_budget_by_pages") or {}).items():
            budget_pages[int(k)] += int(v)
    out = {
        "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_sec": 3600,
        "slots_polled": [str(r.get("slot")) for r in rows],
        "per_slot": rows,
        "upvote_refresh_end_measured_60m": {
            "log_ended_modes_sum_slots": dict(log_all),
            "log_budget_ended_sum_slots": int(log_all.get("budget", 0)),
            "log_budget_pages_distribution": dict(sorted(budget_pages.items())),
            "log_first_held_upvote_sum_slots": int(log_all.get("first_held_upvote", 0)),
            "log_hasNextPage_false_sum_slots": int(log_all.get("hasNextPage_false", 0)),
            "note": "Log tail is last 2 run logs per slot (not strict 60m). Post-patch expect budget→0 and first_held_upvote↑.",
        },
    }
    art.mkdir(parents=True, exist_ok=True)
    path = art / "refresh_end_reasons.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())