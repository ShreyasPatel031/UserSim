#!/usr/bin/env bash
# Merge refresh_priority_<day>.txt (in order) then activity-ordered refresh_upvotes_*.txt tail (deduped).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "${PACE_ENV_FILE:-$ROOT/results/ph_fleet_full/20261108t082000z/pace.env}"
export GCP_PROJECT MVP_GCS_BUCKET
TAG="${1:-$(date -u +%Y%m%dT%H%MZ)}"
PRIORITY_DAYS="${REFRESH_PRIORITY_DAYS:-2026-11-13 2026-11-14 2026-11-15}"
TAIL_GCS="${REFRESH_TAIL_GCS:-usersim_sim/raw/_cursor/refresh_upvotes_20261116T0145Z_fleet.txt}"
OUT_OBJ="usersim_sim/raw/_cursor/refresh_upvotes_${TAG}_priority_merged.txt"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export MERGE_TMP="$TMP" MERGE_BUCKET="$MVP_GCS_BUCKET" MERGE_DAYS="$PRIORITY_DAYS" \
  MERGE_TAIL="$TAIL_GCS" MERGE_OUT="$OUT_OBJ"
python3 <<'PY'
import json, os, subprocess
from pathlib import Path

tmp = Path(os.environ["MERGE_TMP"])
bucket = os.environ["MERGE_BUCKET"]
days = [d for d in os.environ.get("MERGE_DAYS", "").split() if d.strip()]
tail = os.environ["MERGE_TAIL"]
out = os.environ["MERGE_OUT"]
sections = []
seen: set[str] = set()
lines: list[str] = []


def load_gcs(obj: str, dest: Path) -> None:
    subprocess.run(
        ["gcloud", "storage", "cp", f"gs://{bucket}/{obj}", str(dest)],
        check=True,
        capture_output=True,
    )


def add_handles(path: Path, label: str) -> int:
    n = 0
    lines.append(f"# section {label}")
    for ln in path.read_text().splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        h = ln.strip().split()[0].lower().lstrip("@")
        if not h or h in seen:
            continue
        seen.add(h)
        lines.append(h)
        n += 1
    return n


for day in days:
    obj = f"usersim_sim/raw/_cursor/refresh_priority_{day}.txt"
    dest = tmp / f"priority_{day}.txt"
    load_gcs(obj, dest)
    cnt = add_handles(dest, f"refresh_priority_{day}.txt")
    sections.append({"day": day, "gcs": obj, "handles": cnt})

tail_path = tmp / "tail.txt"
load_gcs(tail, tail_path)
tail_n = add_handles(tail_path, tail)
sections.append({"tail": tail, "handles": tail_n})
merged = tmp / "merged.txt"
merged.write_text("\n".join(lines) + "\n")
subprocess.run(
    ["gcloud", "storage", "cp", str(merged), f"gs://{bucket}/{out}"],
    check=True,
    capture_output=True,
)
meta = {
    "out_gcs": f"gs://{bucket}/{out}",
    "out_basename": Path(out).name,
    "total_handles": len(seen),
    "sections": sections,
}
print(json.dumps(meta))
PY
echo "MERGED gs://${MVP_GCS_BUCKET}/${OUT_OBJ}"