#!/usr/bin/env bash
# Weekly close (route-4 "Last week") on a fleet VM with Camoufox — not on the cloud-agent image.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-20261108t082000z}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
export ART
PRIMARY="${PH_WEEKLY_CLOSE_SLOT:-9}"
FALLBACK="${PH_WEEKLY_CLOSE_FALLBACK_SLOT:-27}"
MAX_POSTS="${PH_WEEKLY_CLOSE_MAX_POSTS:-0}"
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
if [[ -d /home/ubuntu/.cache ]]; then
  sudo chown -R ubuntu:ubuntu /home/ubuntu/.cache 2>/dev/null || true
fi
TMP=/tmp/ph_weekly_close_\$\$
mkdir -p "\$TMP"
mkdir -p "\$TMP/boxbrowser" "\$TMP/live"
gcloud storage cp -q "${TOOLS}/bb_capture.py" "${TOOLS}/bb_load.py" "\$TMP/boxbrowser/"
gcloud storage cp -q "${CODE_LIVE}/phparse.py" "${CODE_LIVE}/v2parse.py" "\$TMP/live/"
/opt/venv/bin/python -c "from camoufox.sync_api import Camoufox"
/opt/venv/bin/python "\$TMP/boxbrowser/bb_capture.py" --day "${DAY}" --gap 15 --max-posts ${MAX_POSTS} --no-load
echo weekly_close_fleet_vm ok day=${DAY}
EOS
)
set +e
OUT="$("${GC[@]}" compute ssh "$NAME" --zone="$ZONE" --tunnel-through-iap --quiet \
  --ssh-flag=-oConnectTimeout=30 </dev/null --command="$CMD" 2>&1)"
RC=$?
set -e
printf '%s\n' "$OUT"
# Weekly capture runs on the same VM as repullupvotes (slot 9); restore phsuper after SSH job.
UPVOTE_SLOTS="${FLEET_UPVOTE_SLOTS:-${UPVOTE_SLOTS:-9 27 38}}"
if [[ " $UPVOTE_SLOTS " == *" $SLOT "* ]]; then
  GO_FILE="$ART/upvote_go.token"
  if [[ -s "$GO_FILE" ]]; then
    GO="$(tr -d '\n' <"$GO_FILE")"
    VM_GCS="${PACE_VM_GCS:-gs://${BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"
    STRAT="$ROOT/scripts/vm/ph_strategies/fleet_upvote_refresh.env"
    echo "$GO" | "${GC[@]}" storage cp - "${VM_GCS}/GO.${NAME}" >/dev/null 2>&1 || true
    "${GC[@]}" compute instances add-metadata "$NAME" --zone="$ZONE" \
      --metadata-from-file="ph-strategy-env=$STRAT" >/dev/null 2>&1 || true
    RECOVER='sudo cp -f /opt/ph/strategy.env /opt/ph/strategy.env.bak_weekly 2>/dev/null; B=$(grep -E "^PACE_GCS_VM_ROOT=" /opt/ph/pace.env | cut -d= -f2-); gcloud storage cp -q "$B/_code/overlays/fleet_upvote_refresh.env" /tmp/fleet_upvote_refresh.env 2>/dev/null; sudo cp -f /tmp/fleet_upvote_refresh.env /opt/ph/strategy.env 2>/dev/null; sudo systemctl stop phsuper 2>/dev/null; sudo pkill -f "[p]h_batch.py" 2>/dev/null || true; EA=""; [[ -f /opt/ph/pace.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/pace.env"; [[ -f /opt/ph/strategy.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/strategy.env"; sudo systemd-run --unit=phsuper --collect -p WorkingDirectory=/opt/ph/reuse $EA /bin/bash -c "bash /opt/ph/overlays/supervisor_strat.sh >>/opt/ph/reuse/supervisor.log 2>&1"; sleep 2; pgrep -af ph_batch | head -1 || echo weekly_close_refresh_recover_no_batch'
    "${GC[@]}" compute ssh "$NAME" --zone="$ZONE" --tunnel-through-iap --quiet \
      --ssh-flag=-oConnectTimeout=20 </dev/null --command="$RECOVER" 2>/dev/null | tail -2 || true
    echo "$(date -u +%FT%TZ) weekly_close refresh supervisor recover slot=$SLOT" >&2
  fi
fi
CLOSE_SOURCE="route4_boxbrowser"
if grep -qE "Cloudflare check did not clear|BLOCK challenge|PermissionError.*workspace" <<<"$OUT"; then
  echo "$(date -u +%FT%TZ) weekly_close route4_blocked slot=$SLOT -> api_weekly_ranks" >&2
  bash "$ROOT/scripts/vm/ph_weekly_close_api.sh" "$DAY"
  CLOSE_SOURCE="official_api_weekly_ranks"
elif [[ "$RC" -eq 0 ]]; then
  LOCAL_OUT="/tmp/ph_bb_loaded_${DAY}"
  mkdir -p "$LOCAL_OUT"
  TMP_BB="$(mktemp -d)"
  gcloud storage cp -q "${TOOLS}/bb_load.py" "${TOOLS}/bb_capture.py" "$TMP_BB/" 2>/dev/null || true
  if [[ -f "$TMP_BB/bb_load.py" ]]; then
  PY="${ROOT}/.venv/bin/python"
  [[ -x "$PY" ]] || PY="$(command -v python3)"
  "$PY" "$TMP_BB/bb_load.py" --autoload --local-out "$LOCAL_OUT" 2>/dev/null || true
  fi
  rm -rf "$TMP_BB"
fi
NOTE_JSON="$ART/weekly_close_source.json"
python3 - "$NOTE_JSON" "$DAY" "$SLOT" "$CLOSE_SOURCE" <<'PY'
import json, sys
from datetime import datetime, timezone
path, day, slot, src = sys.argv[1:5]
doc = {
    "read_date_PT": day,
    "close_source": src,
    "fleet_slot": int(slot),
    "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
open(path, "w").write(json.dumps(doc, indent=2) + "\n")
print(path)
PY
echo "weekly_close fleet slot=$SLOT (primary=$PRIMARY fallback=$FALLBACK) day=$DAY close_source=$CLOSE_SOURCE rc=$RC"