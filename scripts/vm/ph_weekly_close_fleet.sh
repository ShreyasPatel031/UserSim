#!/usr/bin/env bash
# Weekly close (route-4 "Last week") on a fleet VM with Camoufox — not on the cloud-agent image.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
PRIMARY="${PH_WEEKLY_CLOSE_SLOT:-26}"
FALLBACK="${PH_WEEKLY_CLOSE_FALLBACK_SLOT:-30}"
DAY="${1:-$(TZ=America/Los_Angeles date +%F)}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:?}"
BUCKET="${MVP_GCS_BUCKET:?}"
TOOLS="gs://${BUCKET}/usersim_sim/raw/ph_at_launch/live/tools/boxbrowser"
CODE_LIVE="gs://${BUCKET}/usersim_sim/raw/ph_at_launch/code/live"

pick_weekly_slot() {
  local s state
  for s in "$PRIMARY" "$FALLBACK"; do
    state="$(PACE_FLEET_RUN_ID="$RUN_ID" python3 - "$ROOT" "$s" <<'PY' 2>/dev/null || echo ok
import json, os, subprocess, sys
root, slot = sys.argv[1], int(sys.argv[2])
env = {**os.environ, "PACE_FLEET_RUN_ID": os.environ.get("PACE_FLEET_RUN_ID", "")}
try:
    m = json.loads(subprocess.check_output(["python3", f"{root}/scripts/vm/ph_fleet_measure.py"], text=True, env=env, cwd=root))
except Exception:
    print("ok")
    raise SystemExit(0)
for r in m.get("slots", []):
    if str(r.get("slot")) == str(slot):
        st = r.get("state") or "unknown"
        if st == "cf_wall":
            print("cf_wall")
        elif st in ("dead", "probe_fail"):
            print("unhealthy")
        else:
            print("ok")
        raise SystemExit(0)
print("ok")
PY
)"
    local st
    st="$("${GC[@]}" compute instances describe "feeder-fleet-${RUN_ID}-${s}" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
    if [[ "$st" != RUNNING ]]; then
      echo "$(date -u +%FT%TZ) weekly_close skip slot=$s vm_status=$st" >&2
      continue
    fi
    if [[ "$state" == ok ]]; then
      echo "$s"
      return 0
    fi
    echo "$(date -u +%FT%TZ) weekly_close skip slot=$s measure_state=$state" >&2
  done
  echo "$FALLBACK"
}

SLOT="$(pick_weekly_slot)"
NAME="feeder-fleet-${RUN_ID}-${SLOT}"
CMD=$(cat <<EOS
set -e
TMP=/tmp/ph_weekly_close_\$\$
mkdir -p "\$TMP"
mkdir -p "\$TMP/boxbrowser" "\$TMP/live"
gcloud storage cp -q "${TOOLS}/bb_capture.py" "${TOOLS}/bb_load.py" "\$TMP/boxbrowser/"
gcloud storage cp -q "${CODE_LIVE}/phparse.py" "${CODE_LIVE}/v2parse.py" "\$TMP/live/"
/opt/venv/bin/python -c "from camoufox.sync_api import Camoufox"
/opt/venv/bin/python "\$TMP/boxbrowser/bb_capture.py" --day "${DAY}" --gap 15 --max-posts 0
echo weekly_close_fleet_vm ok day=${DAY}
EOS
)
"${GC[@]}" compute ssh "$NAME" --zone="$ZONE" --tunnel-through-iap --quiet \
  --ssh-flag=-oConnectTimeout=30 </dev/null --command="$CMD"
echo "weekly_close fleet slot=$SLOT (primary=$PRIMARY fallback=$FALLBACK) day=$DAY"