#!/usr/bin/env bash
# Partition refresh_upvotes_*.txt into repull_upvotes_list.{vm}.txt on GCS for repullupvotes mode.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt")}"
RUN_ID="${RUN_ID,,}"
REFRESH="${1:-usersim_sim/raw/_cursor/refresh_upvotes_20261112T2300Z.txt}"
PREFIX="usersim_sim/raw/ph_population/people_live/vm"
read -r -a slots <<< "${UPVOTE_SLOTS:-9 27 38}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
gcloud storage cp "gs://${MVP_GCS_BUCKET}/${REFRESH}" "$TMP/refresh.txt"
export SEED_TMP="$TMP" SEED_SLOTS="${slots[*]}" SEED_RUN="$RUN_ID"
python3 <<'PY'
import os
from pathlib import Path
tmp = os.environ["SEED_TMP"]
slots = [s.strip() for s in os.environ.get("SEED_SLOTS", "").split() if s.strip()]
run = os.environ["SEED_RUN"]
ns = max(1, len(slots))
handles = []
for ln in Path(f"{tmp}/refresh.txt").read_text().splitlines():
    s = ln.strip()
    if not s or s.startswith("#"):
        continue
    h = s.split()[0].lower().lstrip("@")
    if h:
        handles.append(h)
for i, slot in enumerate(slots):
    part = [h for j, h in enumerate(handles) if j % ns == i]
    Path(f"{tmp}/repull_upvotes_list.feeder-fleet-{run}-{slot}.txt").write_text(
        "\n".join(part) + ("\n" if part else "")
    )
    print(f"slot={slot} n={len(part)}")
print(f"total_handles={len(handles)} slots={ns}")
PY
for slot in "${slots[@]}"; do
  vm="feeder-fleet-${RUN_ID}-${slot}"
  gcloud storage cp "$TMP/repull_upvotes_list.${vm}.txt" \
    "gs://${MVP_GCS_BUCKET}/${PREFIX}/repull_upvotes_list.${vm}.txt"
done
echo "SEEDED upvote_refresh slots=${#slots[@]} file=${REFRESH}"