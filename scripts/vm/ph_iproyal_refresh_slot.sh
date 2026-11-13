#!/usr/bin/env bash
# On VM restart / recreate: sync IPRoyal API → purl files; rebind if egress IP changed, else pool-rotate.
# (IPRoyal has no public replace-ip endpoint — refresh = re-read order + assignment rotate.)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PACE_REPO_ROOT="$ROOT"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt" 2>/dev/null)}"
RUN_ID="${RUN_ID,,}"
export PACE_FLEET_RUN_ID="$RUN_ID" FLEET_ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
SLOT="${1:?slot}"
REASON="${2:-restart}"

purl_before="$(python3 "$ROOT/scripts/vm/ph_iproyal_assignments.py" get "$SLOT")"
host_before="$(python3 -c "import urllib.parse as u; print(u.urlparse(open('$purl_before').read().strip()).hostname or '')")"
bash "$ROOT/scripts/vm/ph_iproyal_sync_pool.sh" >/dev/null 2>&1 || true
python3 "$ROOT/scripts/vm/ph_iproyal_assignments.py" init >/dev/null 2>&1 || true
host_after="$(python3 -c "import urllib.parse as u; p='$purl_before'; print(u.urlparse(open(p).read().strip()).hostname or '') if __import__('pathlib').Path(p).is_file() else ''")"

if [[ -n "$host_before" && -n "$host_after" && "$host_before" != "$host_after" ]]; then
  echo "iproyal_refresh slot=$SLOT api_ip_change $host_before -> $host_after"
  bash "$ROOT/scripts/vm/ph_iproyal_rotate_slot.sh" "$SLOT" "${REASON}_api" 2>/dev/null || true
  exit 0
fi

# Provider dashboard "new IP on restart" is not in reseller API — rotate within owned pool.
bash "$ROOT/scripts/vm/ph_iproyal_rotate_slot.sh" "$SLOT" "$REASON" || true
