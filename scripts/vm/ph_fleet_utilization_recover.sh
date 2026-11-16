#!/usr/bin/env bash
# Raise active slot count: restart phsuper on dead/cf_wall/stale hung batches (no IPRoyal rotate).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PACE_REPO_ROOT="$ROOT"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt" 2>/dev/null)}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
[[ -f "$ART/fleet_measure.json" ]] || exit 0
MAX="${FLEET_WAKEUP_MAX:-10}"
STALE_AGE="${FLEET_STALE_AGE_SEC:-600}"
# Dedicated repullupvotes slots: do not phsuper-restart (would kill upvote_refresh).
FLEET_UPVOTE_SLOTS="${FLEET_UPVOTE_SLOTS:-${UPVOTE_SLOTS:-9 27 38}}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:?}"
VM_GCS="${PACE_GCS_VM_ROOT:-gs://${MVP_GCS_BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"
TS="$(date +%s)"

mapfile -t targets < <(python3 - <<PY
import json
from pathlib import Path
m=json.loads(Path("$ART/fleet_measure.json").read_text())
dead, cf, stale = [], [], []
age_min = int("${STALE_AGE}")
for s in m.get("slots", []):
    slot=int(s.get("slot") or 0)
    st=s.get("state") or ""
    age=s.get("age") if s.get("age") is not None else -1
    wc=int(s.get("win_complete") or 0)
    if st == "dead":
        dead.append(slot)
    elif st == "cf_wall" and s.get("batch"):
        cf.append(slot)
    elif (
        st == "stale"
        and s.get("batch")
        and wc == 0
        and age >= age_min
    ):
        stale.append(slot)
# dead, then hung stale (batch alive, no person row in 10m), then cf_wall
ordered = dead + sorted(stale, key=lambda x: -next(
    (ss.get("age") or 0 for ss in m.get("slots", []) if int(ss.get("slot") or 0) == x), 0
)) + cf
_skip = {int(x) for x in """$FLEET_UPVOTE_SLOTS""".split() if x.strip().isdigit()}
_filt = [x for x in ordered if int(x) not in _skip]
print("\\n".join(str(x) for x in _filt[: int("$MAX")]))
PY
)

REMOTE_KICK='sudo rm -f /opt/ph/reuse/cf_cooldown_until /opt/ph/reuse/cf_backoff_n /opt/ph/reuse/same_tok_retry_at /opt/ph/reuse/iproyal_rotate_request /opt/ph/reuse/last_token /opt/ph/reuse/KICK /opt/ph/reuse/port_override 2>/dev/null
pgrep -f "[p]h_batch.py|[p]deep.py" >/dev/null || sudo systemctl restart phsuper'

REMOTE_STALE='set -e
sudo rm -f /opt/ph/reuse/cf_cooldown_until /opt/ph/reuse/cf_backoff_n /opt/ph/reuse/same_tok_retry_at /opt/ph/reuse/iproyal_rotate_request /opt/ph/reuse/last_token /opt/ph/reuse/KICK /opt/ph/reuse/port_override 2>/dev/null || true
sudo systemctl stop phsuper 2>/dev/null || true
sudo pkill -TERM -f "[p]deep.py|[p]h_batch.py" 2>/dev/null || true
sudo pkill -TERM -f "[c]amoufox" 2>/dev/null || true
sleep 2
EA=""; [[ -f /opt/ph/pace.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/pace.env"; [[ -f /opt/ph/strategy.env ]] && EA="$EA -p EnvironmentFile=/opt/ph/strategy.env"
sudo systemd-run --unit=phsuper --collect -p WorkingDirectory=/opt/ph/reuse $EA /bin/bash -c "bash /opt/ph/overlays/supervisor_strat.sh >> /opt/ph/reuse/supervisor.log 2>&1" >/dev/null 2>&1
sleep 1
pgrep -f "[p]deep.py" >/dev/null && echo STALE_UNHANG_OK || echo STALE_UNHANG_STARTING
exit 0'

n=0
nu=0
for slot in "${targets[@]}"; do
  [[ -z "$slot" ]] && continue
  if [[ " ${FLEET_UPVOTE_SLOTS} " == *" $slot "* ]]; then
    echo "skip_upvote_refresh slot=$slot"
    continue
  fi
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || continue
  use_stale=0
  python3 -c "
import json
from pathlib import Path
m=json.loads(Path('$ART/fleet_measure.json').read_text())
for s in m.get('slots',[]):
  if int(s.get('slot') or 0)==int('$slot') and s.get('state')=='stale' and s.get('batch'):
    raise SystemExit(0)
raise SystemExit(1)
" 2>/dev/null && use_stale=1
  if [[ "$use_stale" == 1 ]]; then
    tok="pdeep:fleet-${RUN_ID}-recover-${TS}-${slot}"
    echo "$tok" | "${GC[@]}" storage cp - "${VM_GCS}/GO.${name}" >/dev/null 2>&1 || true
    "${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet \
      --ssh-flag=-oConnectTimeout=12 </dev/null --command="$REMOTE_STALE" 2>/dev/null && {
      echo "stale_unhang slot=$slot token=$tok"
      nu=$((nu + 1))
    } &
  else
    "${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet \
      --ssh-flag=-oConnectTimeout=12 </dev/null --command="$REMOTE_KICK" 2>/dev/null && {
      echo "wakeup slot=$slot"
      n=$((n + 1))
    } &
  fi
  if (((n + nu) % 5 == 0)); then wait; fi
done
wait
echo "fleet_wakeup n=$n stale_unhang n=$nu"
