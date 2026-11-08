#!/usr/bin/env bash
# Measure realized ppm, shed idle VMs, right-size toward 20/min (max 30).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
export GCP_PROJECT PACE_ZONE MVP_GCS_BUCKET
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt")}"
RUN_ID="${RUN_ID,,}"
export PACE_FLEET_RUN_ID="$RUN_ID"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
export FLEET_ART="$ART"
export FLEET_TARGET_LO="${FLEET_TARGET_LO:-20}"
export FLEET_TARGET_HI="${FLEET_TARGET_HI:-30}"
export FLEET_MAX_VMS="${FLEET_MAX_VMS:-30}"
export FLEET_MIN_VMS="${FLEET_MIN_VMS:-4}"
export PH_FLEET_STRATEGY="$ROOT/scripts/vm/ph_strategies/fleet_optimize.env"

chmod +x "$ROOT/scripts/vm/ph_fleet_roll_patches.sh" "$ROOT/scripts/vm/ph_fleet_measure.py" 2>/dev/null || true

measure_json="$(python3 "$ROOT/scripts/vm/ph_fleet_measure.py")"
echo "$measure_json"

python3 - <<'PY'
import json, os, subprocess, sys
from pathlib import Path
snap = json.loads(os.environ["MEASURE_JSON"])
art = Path(os.environ["FLEET_ART"])
target_lo = float(os.environ.get("FLEET_TARGET_LO", "20"))
max_v = int(os.environ.get("FLEET_MAX_VMS", "30"))
min_v = int(os.environ.get("FLEET_MIN_VMS", "4"))
n = snap["vms"]
realized = snap["realized_ppm"]
need = int(snap.get("vms_needed_for_20") or n)
# desired fleet: enough for 20/min with small headroom, cap at max
desired = max(min_v, min(max_v, need + 1))
if realized >= target_lo and snap["productive_vms"] >= need:
    desired = max(min_v, min(n, need + 1))
rows = snap.get("slots") or []

def shed_candidates():
    out = []
    for r in rows:
        st = r.get("state")
        slot = r["slot"]
        if st in ("cf_wall", "cold", "dead", "probe_fail"):
            if (r.get("n") or 0) <= 2 and (r.get("age", -1) < 0 or r.get("age", 0) > 600):
                out.append(slot)
        elif st == "stale" and (r.get("ppm") or 0) < 0.05 and (r.get("age") or 0) > 1200:
            out.append(slot)
    return sorted(out, reverse=True)

shed = shed_candidates()
to_drop = max(0, n - desired)
actions = []
for slot in shed[:to_drop]:
    actions.append(("delete", slot))
root = Path(os.environ["ROOT"])
if actions:
    autoscale = root / "scripts/vm/ph_fleet_autoscale.sh"
    for _, slot in actions:
        # delete highest idle slots via autoscale delete_one pattern — use scale-to
        pass
print(json.dumps({"realized": realized, "desired_vms": desired, "shed_candidates": shed[:8], "n": n, "need": need}))
PY

# Scale via autoscale (uses flock)
MEASURE_JSON="$measure_json" ROOT="$ROOT" FLEET_ART="$ART" \
  python3 - <<'PY'
import json, os, subprocess
snap = json.loads(os.environ["MEASURE_JSON"])
n, realized = snap["vms"], snap["realized_ppm"]
need = int(snap.get("vms_needed_for_20") or n)
target_lo = float(os.environ.get("FLEET_TARGET_LO", "20"))
max_v = int(os.environ.get("FLEET_MAX_VMS", "30"))
min_v = int(os.environ.get("FLEET_MIN_VMS", "4"))
desired = max(min_v, min(max_v, need + 1 if realized < target_lo else need))
if realized >= target_lo:
    desired = max(min_v, min(n, need + 1))
root = os.environ["ROOT"]
asc = f"{root}/scripts/vm/ph_fleet_autoscale.sh"
if n > desired:
    subprocess.run([asc, "scale-to", str(desired)], check=False, env={**os.environ, "PACE_FLEET_RUN_ID": snap["run_id"]})
elif n < desired and realized < target_lo and n < max_v:
    subprocess.run([asc, "scale-to", str(min(desired, n + 2))], check=False, env={**os.environ, "PACE_FLEET_RUN_ID": snap["run_id"]})
print(f"right-size n={n} desired={desired} realized={realized:.2f}")
PY
