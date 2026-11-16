#!/usr/bin/env bash
# Partition completion_queue_*.txt into per-VM pdeep_list on GCS (unblocks FULL pdeep when RR/need_list drained).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_tab_experiment/20261107t170953z/pace.env}"
export GCP_PROJECT MVP_GCS_BUCKET
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$ROOT/results/ph_fleet_full/latest_run.txt")}"
RUN_ID="${RUN_ID,,}"
ART="$ROOT/results/ph_fleet_full/${RUN_ID}"
QUEUE="${1:-usersim_sim/raw/_cursor/completion_queue_20261115T1100Z.txt}"
PREFIX="usersim_sim/raw/ph_population/people_live/vm"
mapfile -t slots < <(awk 'NF && $1 !~ /^#/{print $1}' "$ART/slots.tsv")
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
gcloud storage cp "gs://${MVP_GCS_BUCKET}/${QUEUE}" "$TMP/queue.txt"
HAVE_INDEX="${HAVE_INDEX:-usersim_sim/raw/ph_population/people_live/have_index.jsonl}"
gcloud storage cp "gs://${MVP_GCS_BUCKET}/${HAVE_INDEX}" "$TMP/have_index.jsonl" 2>/dev/null || : >"$TMP/have_index.jsonl"
export SEED_TMP="$TMP" SEED_N="${#slots[@]}" SEED_SLOTS="${slots[*]}"
python3 <<'PY'
import json
import os
import sys
from pathlib import Path
tmp = os.environ["SEED_TMP"]
slots = os.environ.get("SEED_SLOTS", "").split()
ns = max(1, int(os.environ.get("SEED_N", "1") or 1))
complete = set()
for ln in Path(f"{tmp}/have_index.jsonl").read_text().splitlines():
    try:
        j = json.loads(ln)
    except Exception:
        continue
    if not j.get("complete"):
        continue
    h = (j.get("handle") or "").lower().lstrip("@")
    if h:
        complete.add(h)
handles = []
skipped = 0
for ln in Path(f"{tmp}/queue.txt").read_text().splitlines():
    s = ln.strip()
    if not s or s.startswith("#"):
        continue
    h = s.split("\t", 1)[0].split()[0].lower().lstrip("@")
    if not h:
        continue
    if h in complete:
        skipped += 1
        continue
    handles.append(h)
print(f"seed_handles n={len(handles)} skipped_have_complete={skipped}", file=sys.stderr)
for i, slot in enumerate(slots):
    part = [h for j, h in enumerate(handles) if j % ns == i]
    Path(f"{tmp}/pdeep_list.{slot}.txt").write_text("\n".join(part) + ("\n" if part else ""))
    print(f"slot={slot} n={len(part)}", file=sys.stderr)
PY
for slot in "${slots[@]}"; do
  vm="feeder-fleet-${RUN_ID}-${slot}"
  gcloud storage cp "$TMP/pdeep_list.${slot}.txt" "gs://${MVP_GCS_BUCKET}/${PREFIX}/pdeep_list.${vm}.txt"
done
echo "SEEDED pdeep_list slots=${#slots[@]} queue=${QUEUE}"