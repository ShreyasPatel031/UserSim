#!/usr/bin/env bash
# Live capture has strict priority over historical fleet pulls.
# Simulation contract (Grokbot/orchestrator mailbox): official-API posts_ts + snapshots every 15 PT minutes.
# If any monitored live object is stale, throttle historical fleet (yield proxy/VM headroom for daily feeders).
#
#   LIVE_FEED_MAX_GAP_SEC=900   # one missed 15m bucket
#   LIVE_FEED_GRACE_SEC=180     # upload / clock skew
#   ./scripts/vm/ph_fleet_live_priority.sh status
#   ./scripts/vm/ph_fleet_live_priority.sh env   # eval exports for checkin
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=/dev/null
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt" 2>/dev/null || echo 20261108t082000z)}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
mkdir -p "$ART"
export PACE_REPO_ROOT="$ROOT"

export LIVE_FEED_MAX_GAP_SEC="${LIVE_FEED_MAX_GAP_SEC:-900}"
export LIVE_FEED_GRACE_SEC="${LIVE_FEED_GRACE_SEC:-180}"
export IPROYAL_DAILY_IPS="${IPROYAL_DAILY_IPS:-2}"
DAILY_N="$IPROYAL_DAILY_IPS"

status_json="$ART/live_feed_health.json"
throttle_flag="$ART/historical_throttle"

python3 - "$MVP_GCS_BUCKET" "$status_json" "$throttle_flag" "$DAILY_N" <<'PY'
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

bucket, out_path, throttle_path, daily_n = sys.argv[1:5]
daily_n = int(daily_n)
max_gap = int(os.environ.get("LIVE_FEED_MAX_GAP_SEC", "900"))
grace = int(os.environ.get("LIVE_FEED_GRACE_SEC", "180"))
now = datetime.now(timezone.utc)

def pt_today_prefix():
    return now.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")

def gs_ls(prefix: str):
    try:
        r = subprocess.run(
            ["gsutil", "ls", "-l", f"gs://{bucket}/{prefix}"],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except Exception as e:
        return None, str(e)
    if r.returncode != 0:
        return None, (r.stderr or r.stdout or "gsutil failed").strip()
    latest = None
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("TOTAL:"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            size = int(parts[0])
        except ValueError:
            continue
        ts_s = parts[1]
        obj = parts[-1]
        try:
            mtime = datetime.strptime(ts_s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if latest is None or mtime > latest[0]:
            latest = (mtime, obj, size)
    return latest, None

day = pt_today_prefix()
base = f"usersim_sim/raw/ph_at_launch/{day}"

feeds = [
    ("posts_ts", f"{base}/live/posts_ts.jsonl", "mtime"),
    ("coverage_ts", f"{base}/live/coverage_ts.jsonl", "mtime"),
    ("snapshots", f"{base}/snapshots/", "prefix_latest"),
    ("api_comments", f"{base}/api_comments/", "prefix_latest"),
]

CRITICAL_FEEDS = frozenset({"posts_ts", "snapshots"})

rows = []
any_stale = False
critical_stale = False
worst_age = 0.0

for name, path, kind in feeds:
    latest, err = gs_ls(path)
    row = {"feed": name, "path": f"gs://{bucket}/{path}", "ok": False}
    if err:
        row["error"] = err
        row["stale"] = True
        any_stale = True
        if name in CRITICAL_FEEDS:
            critical_stale = True
        rows.append(row)
        continue
    if not latest:
        row["error"] = "no_objects"
        row["stale"] = True
        any_stale = True
        if name in CRITICAL_FEEDS:
            critical_stale = True
        rows.append(row)
        continue
    mtime, obj, size = latest
    age = (now - mtime).total_seconds()
    limit = max_gap + grace
    stale = age > limit
    row.update(
        {
            "latest_utc": mtime.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "age_sec": round(age, 1),
            "max_age_sec": limit,
            "object": obj,
            "bytes": size,
            "stale": stale,
            "ok": not stale,
        }
    )
    if stale:
        any_stale = True
        if name in CRITICAL_FEEDS:
            critical_stale = True
    worst_age = max(worst_age, age)
    rows.append(row)

pool_lines = 0
root = Path(os.environ.get("PACE_REPO_ROOT", str(Path.cwd())))
pool = Path(os.environ.get("PACE_IPROYAL_POOL", str(root / "secrets/iproyal.pool")))
if not pool.is_absolute():
    pool = root / pool
if pool.exists():
    pool_lines = sum(
        1
        for ln in pool.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    )

hist_cap = max(0, pool_lines - daily_n) if pool_lines else int(os.environ.get("FLEET_MAX_VMS", "20"))
throttle = critical_stale
throttle_max = int(os.environ.get("FLEET_LIVE_THROTTLE_MAX_VMS", str(hist_cap)))
throttle_min = int(os.environ.get("FLEET_LIVE_THROTTLE_MIN_VMS", str(min(4, throttle_max))))

report = {
    "utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "pt_day": day,
    "simulation_cadence_sec": max_gap,
    "simulation_note": (
        "Orchestrator (grokbot): monthly_rank_at_fetch on every live posts_ts row at each 15-min snapshot "
        "(official API). >15m gap = missing time-series bucket for prediction/simulation."
    ),
    "feeds": rows,
    "any_stale": any_stale,
    "critical_stale": critical_stale,
    "worst_age_sec": round(worst_age, 1),
    "ip_pool_total": pool_lines,
    "ip_daily_reserved": daily_n,
    "historical_slot_cap": hist_cap,
    "throttle": throttle,
    "throttle_fleet_max_vms": throttle_max if throttle else None,
    "throttle_fleet_min_vms": throttle_min if throttle else None,
}
Path(out_path).write_text(json.dumps(report, indent=2) + "\n")
if throttle:
    Path(throttle_path).write_text(now.strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")
else:
    Path(throttle_path).unlink(missing_ok=True)
PY

cmd="${1:-status}"
case "$cmd" in
  status)
    cat "$status_json" 2>/dev/null || true
    ;;
  env)
    python3 -c "
import json
from pathlib import Path
p=Path('$status_json')
if not p.exists():
    print('PH_FLEET_LIVE_PRIORITY_HOLD=0')
    raise SystemExit(0)
r=json.loads(p.read_text())
if r.get('throttle'):
    tmin=int(r.get('throttle_fleet_min_vms') or 4)
    print(f'export PH_FLEET_LIVE_PRIORITY_HOLD=1')
    print(f'export FLEET_MIN_VMS={tmin}')
    print(f'export FLEET_MAX_VMS={tmin}')
    print(f'export FLEET_AUTOSCALE_NO_SHED=1')
    print(f'export FLEET_HISTORICAL_THROTTLE=1')
    print(f'export KEEPER_NUDGE_BUDGET=0')
    print(f'export FLEET_CF_RECOVER_MAX_KICKS=0')
    stale=[f[\"feed\"] for f in r.get(\"feeds\",[]) if f.get(\"stale\")]
    print(f'export PH_FLEET_LIVE_STALE_FEEDS=\"{\",\".join(stale)}\"')
elif r.get('any_stale'):
    stale=[f[\"feed\"] for f in r.get(\"feeds\",[]) if f.get(\"stale\")]
    print(f'export PH_FLEET_LIVE_SECONDARY_STALE=\"{\",\".join(stale)}\"')
    print('export PH_FLEET_LIVE_PRIORITY_HOLD=0')
    cap=r.get('historical_slot_cap')
    if cap and cap>0:
        print(f'export FLEET_MAX_VMS={cap}')
else:
    pool=r.get('ip_pool_total') or 0
    daily=r.get('ip_daily_reserved') or $DAILY_N
    cap=r.get('historical_slot_cap')
    if cap and cap>0:
        print(f'export FLEET_MAX_VMS={cap}')
    print('export PH_FLEET_LIVE_PRIORITY_HOLD=0')
    print('export FLEET_HISTORICAL_THROTTLE=0')
    print('export PH_FLEET_LIVE_STALE_FEEDS=')
"
    ;;
  *)
    echo "usage: $0 status|env" >&2
    exit 2
    ;;
esac
