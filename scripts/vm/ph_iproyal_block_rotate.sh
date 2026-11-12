#!/usr/bin/env bash
# After sustained CF/block: rotate Finland slots to a different dedicated IP (not same-IP cooldown).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PACE_REPO_ROOT="$ROOT"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt" 2>/dev/null)}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
export PACE_FLEET_RUN_ID="$RUN_ID" FLEET_ART="$ART"
MAX="${IPROYAL_BLOCK_ROTATE_MAX:-4}"
WALLS_MIN="${IPROYAL_BLOCK_ROTATE_WALLS:-2}"
[[ -f "$ART/fleet_measure.json" ]] || exit 0
bash "$ROOT/scripts/vm/ph_iproyal_sync_pool.sh" >/dev/null 2>&1 || true
python3 "$ROOT/scripts/vm/ph_iproyal_assignments.py" init >/dev/null 2>&1 || true

mapfile -t targets < <(python3 - <<PY
import json
from pathlib import Path
art = Path("$ART")
m = json.loads((art / "fleet_measure.json").read_text())
walls_min = int("$WALLS_MIN")
out = []
for s in m.get("slots", []):
    slot = int(s.get("slot") or 0)
    if slot <= 1:
        continue
    st = s.get("state") or ""
    walls = int(s.get("walls") or 0)
    wc = int(s.get("win_complete") or 0)
    ppm = float(s.get("ppm_complete") or s.get("ppm") or 0)
    if st in ("cf_wall", "dead") or (walls >= walls_min and wc == 0 and ppm < 0.15):
        out.append(str(slot))
print("\\n".join(out[:20]))
PY
)

n=0
for slot in "${targets[@]}"; do
  [[ -z "$slot" ]] && continue
  (( n >= MAX )) && break
  bash "$ROOT/scripts/vm/ph_iproyal_rotate_slot.sh" "$slot" "sustained_block" && n=$((n + 1))
done

SA="${PACE_SERVICE_ACCOUNT:-usersim-cloud-agent@${GCP_PROJECT}.iam.gserviceaccount.com}"
GC=(gcloud --account="$SA")
ZONE="${PACE_ZONE:?}"
while IFS=$'\t' read -r slot _; do
  [[ -z "$slot" || "$slot" == "1" ]] && continue
  (( n >= MAX )) && break
  name="feeder-fleet-${RUN_ID}-${slot}"
  st="$("${GC[@]}" compute instances describe "$name" --zone="$ZONE" --format='value(status)' 2>/dev/null || echo MISSING)"
  [[ "$st" == RUNNING ]] || continue
  req="$("${GC[@]}" compute ssh "$name" --zone="$ZONE" --tunnel-through-iap --quiet </dev/null \
    --command='test -f /opt/ph/reuse/iproyal_rotate_request && cat /opt/ph/reuse/iproyal_rotate_request' 2>/dev/null || true)"
  [[ -n "$req" ]] || continue
  bash "$ROOT/scripts/vm/ph_iproyal_rotate_slot.sh" "$slot" "vm_block_request" && n=$((n + 1))
done <"$ART/slots.tsv"
echo "iproyal_block_rotate n=$n"
