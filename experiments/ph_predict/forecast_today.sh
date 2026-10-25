#!/bin/bash
# Forecast a live day's leaderboard: fetch its featured launches, find their websites, score them.
# usage: ./forecast_today.sh 2026-10-26   (Pacific date; run after the morning's launches are featured)
set -euo pipefail
cd "$(dirname "$0")"
D=${1:?date}
python3 today.py "$D"
NO_WB=1 python3 - "$D" <<'PY'
import json, os, sys, resolve_sites as R
d = sys.argv[1]
out = "data/sites_today.jsonl"
done = {json.loads(l)["id"] for l in open(out)} if os.path.exists(out) else set()
with open(out, "a") as f:
    for p in json.load(open(f"data/today/{d}.json")):
        if p["id"] not in done:
            p["_date"] = d; R.one(p, f)
PY
python3 external.py x
python3 forecast.py "$D"
