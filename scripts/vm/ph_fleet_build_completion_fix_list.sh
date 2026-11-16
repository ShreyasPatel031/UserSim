#!/usr/bin/env bash
# Build fix_completion_queue_* from completion_queue, minus have_index complete=true (orchestrator 16:35Z).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export GCP_PROJECT MVP_GCS_BUCKET
QUEUE="${1:-}"
if [[ -z "$QUEUE" ]]; then
  QUEUE="$(gcloud storage ls "gs://${MVP_GCS_BUCKET}/usersim_sim/raw/_cursor/completion_queue_"*.txt 2>/dev/null | tail -1 || true)"
  QUEUE="${QUEUE##gs://${MVP_GCS_BUCKET}/}"
fi
[[ -n "$QUEUE" ]] || { echo "no completion_queue" >&2; exit 1; }
HAVE_INDEX="${HAVE_INDEX:-usersim_sim/raw/ph_population/people_live/have_index.jsonl}"
TAG="${2:-$(date -u +%Y%m%dT%H%MZ)}"
OUT="usersim_sim/raw/_cursor/fix_completion_queue_${TAG}.txt"
FIX_BASENAME="fix_completion_queue_${TAG}.txt"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
gcloud storage cp "gs://${MVP_GCS_BUCKET}/${QUEUE}" "$TMP/queue.txt"
gcloud storage cp "gs://${MVP_GCS_BUCKET}/${HAVE_INDEX}" "$TMP/have_index.jsonl" 2>/dev/null || : >"$TMP/have_index.jsonl"
export BUILD_TMP="$TMP"
python3 <<'PY'
import json, os
from pathlib import Path
tmp = Path(os.environ["BUILD_TMP"])
out = tmp / "fix.txt"
complete = set()
for ln in (tmp / "have_index.jsonl").read_text().splitlines():
    try:
        j = json.loads(ln)
    except Exception:
        continue
    if not j.get("complete"):
        continue
    h = (j.get("handle") or "").lower().lstrip("@")
    if h:
        complete.add(h)
lines_out = []
skipped = 0
for ln in (tmp / "queue.txt").read_text().splitlines():
    if ln.startswith("#") or not ln.strip():
        lines_out.append(ln)
        continue
    h = ln.strip().split("\t", 1)[0].split()[0].lower().lstrip("@")
    if h in complete:
        skipped += 1
        continue
    lines_out.append(ln)
out.write_text("\n".join(lines_out) + "\n")
kept = sum(1 for ln in lines_out if ln.strip() and not ln.startswith("#"))
print(json.dumps({"kept": kept, "skipped_complete": skipped}))
PY
gcloud storage cp "$TMP/fix.txt" "gs://${MVP_GCS_BUCKET}/${OUT}"
echo "BUILT gs://${MVP_GCS_BUCKET}/${OUT} from ${QUEUE}"
echo "FIX_BASENAME=${FIX_BASENAME}"