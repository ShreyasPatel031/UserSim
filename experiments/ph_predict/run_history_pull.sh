#!/bin/bash
# 2024 + 2023 Product Hunt day lists (ph_history_pull.py). Runs on the pipeline VM ONLY after Shreyas's direct yes.
# The token is set exactly as run_daily.sh sets it (from the discovery keys file) and is never echoed.
# The machine powers off at 23:55 PT and nothing may run 00:05-01:00 PT: the script pauses 23:45-01:00 PT; after the machine is back
# (after 01:00 PT) run `start` again; it resumes from the first missing day.
# usage: bash run_history_pull.sh start|stop|status|dry-run [years, default 2024,2023]
set -u
CMD="${1:-status}"; YEARS="${2:-2024,2023}"
HERE="$(cd "$(dirname "$0")" && pwd)"; W="${WORK:-$HOME/w/ph_history}"; export WORK="$W"; mkdir -p "$W"
LOG="$W/pull.log"; PID="$W/pull.pid"; B=gs://usersim-bakeoff-347838016394/usersim_sim/raw/ph_history
running() { [ -s "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; }
case "$CMD" in
  start)
    if running; then echo "already running pid $(cat "$PID")"; exit 0; fi
    export PATH=/opt/exp/bin:$PATH
    export PH_TOKEN=$(python3 -c "import json; print(json.load(open('/var/lib/usersim/discovery_keys.json'))['PH_TOKEN'])")
    setsid nohup python3 "$HERE/ph_history_pull.py" --years "$YEARS" >> "$LOG" 2>&1 < /dev/null &
    echo $! > "$PID"; unset PH_TOKEN; echo "started pid $(cat "$PID"), log $LOG" ;;
  stop)
    if running; then kill "$(cat "$PID")"; echo "stopped pid $(cat "$PID")"; else echo "not running"; fi; rm -f "$PID" ;;
  dry-run)
    python3 "$HERE/ph_history_pull.py" --years "$YEARS" --dry-run ;;
  status)
    running && echo "running pid $(cat "$PID")" || echo "not running"
    for y in ${YEARS//,/ }; do echo "$y bucket days: $(gsutil ls "$B/$y/" 2>/dev/null | grep -c '\.json$') / local: $(ls "$W/$y" 2>/dev/null | grep -c '\.json$')"; done
    [ -s "$LOG" ] && python3 - "$LOG" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.startswith("{")]
days = [r for r in rows if r.get("event") == "day"]
runs = sum(1 for r in rows if r.get("event") == "plan" and not r.get("dry_run"))
# calls restart at 0 on each start: sum the last count of each run
tot, last = 0, 0
for r in rows:
    if r.get("event") == "plan" and not r.get("dry_run"): tot += last; last = 0
    if r.get("event") == "day": last = r["calls"]
print(json.dumps({"runs": runs, "days_fetched": len(days), "calls_used": tot + last, "posts": sum(r["posts"] for r in days),
                  "last_day": days[-1]["day"] if days else None, "last_remaining": days[-1]["remaining"] if days else None,
                  "last_event": rows[-1] if rows else None}))
PY
    ;;
  *) echo "usage: $0 start|stop|status|dry-run [years]"; exit 2 ;;
esac
