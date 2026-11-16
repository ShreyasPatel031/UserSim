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
STALE_AGE="${FLEET_STALE_AGE_SEC:-2400}"
UNHANG_COOLDOWN="${FLEET_UNHANG_COOLDOWN_SEC:-1800}"
COOLDOWN_FILE="$ART/unhang_cooldown.json"
# Dedicated repullupvotes slots: do not phsuper-restart (would kill upvote_refresh).
FLEET_UPVOTE_SLOTS="${FLEET_UPVOTE_SLOTS:-${UPVOTE_SLOTS:-9 27 38}}"
SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:?}"
VM_GCS="${PACE_GCS_VM_ROOT:-gs://${MVP_GCS_BUCKET}/usersim_sim/raw/ph_population/people_live/vm}"
TS="$(date +%s)"
FLEET_SKIP_STALE_UNHANG=0
STALE_UNHANG_MIN="${FLEET_STALE_UNHANG_MIN_COMPLETE_PPM:-6}"
if [[ "${FLEET_HOLD_UNHANG:-0}" == 1 ]]; then
  FLEET_SKIP_STALE_UNHANG=1
  echo "stale_unhang_paused FLEET_HOLD_UNHANG=1 (no stale_unhang loops; dead/cf wakeup still allowed)"
fi
_cur_ppm="$(python3 -c "import json; print(json.load(open('$ART/fleet_measure.json')).get('complete_ppm',0))" 2>/dev/null || echo 0)"
if [[ "${FLEET_SKIP_STALE_UNHANG}" != 1 ]] && python3 -c "exit(0 if float('${_cur_ppm}') < float('$STALE_UNHANG_MIN') else 1)" 2>/dev/null; then
  FLEET_SKIP_STALE_UNHANG=1
  echo "stale_unhang_paused complete_ppm=${_cur_ppm} min=${STALE_UNHANG_MIN}"
fi

mapfile -t targets < <(python3 - <<PY
import json
from pathlib import Path
m=json.loads(Path("$ART/fleet_measure.json").read_text())
dead, cf, stale, stale_warm = [], [], [], []
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
    elif (
        st == "stale"
        and s.get("batch")
        and wc == 0
        and age >= 600
        and age < age_min
    ):
        stale_warm.append(slot)
# dead, then hung stale (batch alive, no person row in 10m), then cf_wall
ordered = dead + sorted(stale, key=lambda x: -next(
    (ss.get("age") or 0 for ss in m.get("slots", []) if int(ss.get("slot") or 0) == x), 0
)) + sorted(stale_warm, key=lambda x: -next(
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
  if int(s.get('slot') or 0)!=int('$slot'):
    continue
  if s.get('state')!='stale' or not s.get('batch'):
    continue
  age=int(s.get('age') or 0)
  if age>=int('$STALE_AGE'):
    raise SystemExit(0)
raise SystemExit(1)
" 2>/dev/null && use_stale=1
  if [[ "$use_stale" == 1 ]]; then
  if [[ "$FLEET_SKIP_STALE_UNHANG" == 1 ]]; then
    continue
  fi
  if python3 -c "
import json, time, sys
from pathlib import Path
p = Path('''$COOLDOWN_FILE''')
d = json.loads(p.read_text()) if p.exists() else {}
last = int(d.get('$slot') or 0)
sys.exit(0 if last and time.time() - last < int('$UNHANG_COOLDOWN') else 1)
" 2>/dev/null; then
    echo "stale_unhang_cooldown slot=$slot"
    continue
  fi
  skip=0
  "${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet \
    --ssh-flag=-oConnectTimeout=12 </dev/null --command='pgrep -f "[p]deep.py|[p]h_batch.py" >/dev/null || exit 1
f=$(ls -t /opt/ph/reuse/run_*.log 2>/dev/null | head -1) || exit 1
find "$f" -mmin -12 2>/dev/null | grep -q . || exit 1
tail -40 "$f" 2>/dev/null | grep -qE "paged|repage|op_seen|Profile" && { echo STALE_SKIP_ACTIVE_PULL; exit 0; }
exit 1' 2>/dev/null | grep -q STALE_SKIP_ACTIVE_PULL && skip=1
  if [[ "$skip" == 1 ]]; then
    echo "stale_skip_active_pull slot=$slot"
    continue
  fi
    tok="pdeep:fleet-${RUN_ID}-recover-${TS}-${slot}"
    echo "$tok" | "${GC[@]}" storage cp - "${VM_GCS}/GO.${name}" >/dev/null 2>&1 || true
    "${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet \
      --ssh-flag=-oConnectTimeout=12 </dev/null --command="$REMOTE_STALE" 2>/dev/null && {
      echo "stale_unhang slot=$slot token=$tok"
      python3 -c "
import json, time
from pathlib import Path
p = Path('''$COOLDOWN_FILE''')
d = json.loads(p.read_text()) if p.exists() else {}
d['$slot'] = int(time.time())
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(d))
" 2>/dev/null || true
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
