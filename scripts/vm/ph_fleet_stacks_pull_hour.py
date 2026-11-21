#!/usr/bin/env python3
"""Measured need-list / pdeep stacks failures in the last hour (fleet VM status + run log)."""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = (os.environ.get("PACE_FLEET_RUN_ID") or "20261108t082000z").lower()
ART = Path(os.environ.get("FLEET_ART") or ROOT / f"results/ph_fleet_full/{RUN_ID}")
OUT = ART / "stacks_pull_hour.json"
ZONE = os.environ["PACE_ZONE"]
PROJ = os.environ["GCP_PROJECT"]
SA = os.environ.get("PACE_SERVICE_ACCOUNT", f"usersim-cloud-agent@{PROJ}.iam.gserviceaccount.com")
WINDOW_SEC = int(os.environ.get("FLEET_STACKS_WINDOW_SEC", "3600"))

PROBE = r"""python3 -c "
import json, glob, socket, re
from datetime import datetime, timezone
W=__WINDOW__
now=datetime.now(timezone.utc).timestamp()
host=socket.gethostname()
attempts=set(); stacks_fail=set()
def ts(u):
  try: return datetime.fromisoformat(u.replace('Z','+00:00')).timestamp()
  except Exception: return None
path='/opt/ph/reuse/status_'+host+'.jsonl'
try:
  for ln in open(path):
    try: j=json.loads(ln)
    except Exception: continue
    h=j.get('handle')
    if not h: continue
    t=ts(j.get('utc') or '')
    if t is None or now-t>W: continue
    meth=str(j.get('method') or '')
    ev=str(j.get('event') or '')
    if meth=='repullupvotes' or 'refresh' in ev: continue
    if j.get('rc') is None and not meth: continue
    attempts.add(h)
    st=(j.get('coverage') or {}).get('stacks') or {}
    if st.get('got')==0:
      stacks_fail.add(h)
    elif float(j.get('header_pct') or 0)<98 and st.get('got') in (0, None):
      stacks_fail.add(h)
except FileNotFoundError: pass
pqnf=0; stacks_first_fail=0; stacks_zero_line=0
logs=sorted(glob.glob('/opt/ph/reuse/run_*.log'))
if logs:
  for ln in open(logs[-1], errors='ignore'):
    if 'ProfileStacksPage' in ln and 'PersistedQueryNotFound' in ln: pqnf+=1
    if 'stacks gql first page failed' in ln: stacks_first_fail+=1
    if re.search(r'stacks 0 of 0 gql pages 0', ln): stacks_zero_line+=1
print(json.dumps({'attempts':len(attempts),'stacks_fail_handles':len(stacks_fail),
  'pqnf_log_lines':pqnf,'stacks_first_page_fail_log':stacks_first_fail,'stacks_zero_log':stacks_zero_line}))
" """.replace("__WINDOW__", str(WINDOW_SEC))


def load_poll_slots() -> list[str]:
    mpath = ART / "fleet_measure.json"
    if not mpath.is_file():
        return []
    m = json.loads(mpath.read_text())
    out: list[str] = []
    for s in m.get("slots") or []:
        st = s.get("state") or ""
        if st in ("probe_fail", "dead", "cold"):
            continue
        if float(s.get("ppm_attempt") or 0) > 0 or int(s.get("win_rerun") or 0) > 0:
            out.append(str(s["slot"]))
        elif st in ("active", "stale") and s.get("batch"):
            out.append(str(s["slot"]))
    return out[:10]


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
                f"--command={PROBE}",
            ],
            capture_output=True,
            text=True,
            timeout=50,
        )
        for ln in r.stdout.splitlines():
            if ln.startswith("{"):
                d = json.loads(ln)
                d["slot"] = int(slot)
                return d
    except Exception as e:
        return {"slot": int(slot), "error": str(e)[:120]}
    return {"slot": int(slot), "error": "no_json"}


def main() -> int:
    slots = load_poll_slots()
    rows: list[dict] = []
    if slots:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            rows = list(ex.map(probe_slot, slots))
    attempts = sum(int(r.get("attempts") or 0) for r in rows)
    stacks_fail = sum(int(r.get("stacks_fail_handles") or 0) for r in rows)
    pqnf = sum(int(r.get("pqnf_log_lines") or 0) for r in rows)
    stacks_first = sum(int(r.get("stacks_first_page_fail_log") or 0) for r in rows)
    stacks_zero = sum(int(r.get("stacks_zero_log") or 0) for r in rows)
    report = {
        "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_sec": WINDOW_SEC,
        "slots_polled": slots,
        "per_slot": rows,
        "need_list_stacks_fail_measured_60m": {
            "pdeep_attempt_handles_sum_slots": attempts,
            "stacks_fail_handles_sum_slots": stacks_fail,
            "note": "Sums across polled slots may double-count if same handle retried; pqnf is live log evidence.",
            "ProfileStacksPage_PersistedQueryNotFound_log_lines": pqnf,
            "stacks_gql_first_page_failed_log_lines": stacks_first,
            "stacks_zero_of_zero_log_lines": stacks_zero,
        },
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())