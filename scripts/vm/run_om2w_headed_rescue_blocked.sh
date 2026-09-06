#!/usr/bin/env bash
# Probe Flash-Lite BLOCKED hosts: chromium_headless vs chromium_headful (Xvfb).
# Reports how many headful unblocks vs headless.
#
# Usage:
#   HOSTS_FILE=results/capability/om2w_flashlite_blocked_hosts.json \
#     ./scripts/vm/run_om2w_headed_rescue_blocked.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}"
ZONE="${GCP_ZONE:-us-central1-b}"
MACHINE="${GCP_MACHINE:-e2-standard-8}"
NAME="${VM_NAME:-usersim-om2w-headed-rescue-$(date +%y%m%d-%H%M%S)}"
WORKERS="${WORKERS:-12}"
TAG="${TAG:-headed_rescue_$(date +%H%M)}"
HOSTS_FILE="${HOSTS_FILE:-results/capability/om2w_flashlite_blocked_hosts.json}"
KEEP_VM="${KEEP_VM:-0}"
GCS_PREFIX="${GCS_PREFIX:-gs://usersim-bakeoff-347838016394}"
SSH=(gcloud compute ssh "$NAME" --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap)
SCP=(gcloud compute scp --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap)

if [[ ! -f "$HOSTS_FILE" ]]; then
  echo "ERROR: HOSTS_FILE missing: $HOSTS_FILE"
  exit 1
fi
if [[ ! -f secrets/env ]]; then
  echo "ERROR: secrets/env missing"
  exit 1
fi

echo "Creating $NAME ($MACHINE) in $ZONE..."
gcloud compute instances create "$NAME" \
  --project="$PROJECT" \
  --zone="$ZONE" \
  --machine-type="$MACHINE" \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=40GB \
  --boot-disk-type=pd-balanced \
  --network=main-vpc \
  --subnet=primary-subnet \
  --scopes=cloud-platform \
  --tags=allow-iap-ssh \
  --quiet

cleanup() {
  if [[ "$KEEP_VM" == "0" ]]; then
    echo "Deleting $NAME..."
    gcloud compute instances delete "$NAME" --project="$PROJECT" --zone="$ZONE" --quiet || true
  fi
}
trap cleanup EXIT

echo "Waiting for SSH..."
for i in $(seq 1 40); do
  if "${SSH[@]}" --command="echo up" --quiet 2>/dev/null; then
    break
  fi
  sleep 5
done

"${SSH[@]}" --command="mkdir -p ~/usersim/secrets ~/usersim/results/capability ~/usersim/data/om2w"
"${SCP[@]}" --recurse "$ROOT/src" "$NAME:~/usersim/" --quiet
"${SCP[@]}" --recurse "$ROOT/data/om2w" "$NAME:~/usersim/data/" --quiet
"${SCP[@]}" "$ROOT/secrets/env" "$NAME:~/usersim/secrets/env" --quiet
"${SCP[@]}" "$HOSTS_FILE" "$NAME:~/usersim/results/capability/blocked_hosts.json" --quiet

"${SSH[@]}" --command="bash -s" <<REMOTE
set -euo pipefail
cd ~/usersim
timeout 180 sudo apt-get update -qq || true
timeout 180 sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3-venv python3-pip xvfb libgtk-3-0 libx11-xcb1 libasound2 >/dev/null
python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q playwright
.venv/bin/playwright install --with-deps chromium
export DISPLAY=:99
pkill -f 'Xvfb :99' 2>/dev/null || true
Xvfb :99 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 &
sleep 1
PYTHONPATH=src .venv/bin/python -m capability.run_om2w_unblock_bakeoff \
  --backends chromium_headless,chromium_headful \
  --hosts-file results/capability/blocked_hosts.json \
  --workers ${WORKERS} --tag ${TAG}
REMOTE

"${SCP[@]}" \
  "$NAME:~/usersim/results/capability/om2w_unblock_${TAG}.json" \
  "$ROOT/results/capability/om2w_unblock_${TAG}.json" --quiet

gcloud storage cp "$ROOT/results/capability/om2w_unblock_${TAG}.json" \
  "${GCS_PREFIX}/om2w_unblock/om2w_unblock_${TAG}.json" --quiet || true

python3 - <<PY
import json
from pathlib import Path
p = Path("results/capability/om2w_unblock_${TAG}.json")
d = json.loads(p.read_text())
s = d["summary"]
hl, hf = s["chromium_headless"], s["chromium_headful"]
print("=== Flash-Lite BLOCKED hosts — headless vs headed ===")
print(f"hosts: {d['n_hosts']}")
print(f"headless OK={hl['ok']}/{hl['n']} ({hl['ok_rate']:.1%})  BLOCKED={hl['blocked']}")
print(f"headed   OK={hf['ok']}/{hf['n']} ({hf['ok_rate']:.1%})  BLOCKED={hf['blocked']}")
rescued = hf.get("rescued_vs_chromium_headless") or []
print(f"headed rescues vs headless: {len(rescued)}")
for h in rescued:
    print(f"  + {h}")
still = sorted(set(hl.get("blocked_hosts") or []) & set(hf.get("blocked_hosts") or []))
print(f"still blocked on both: {len(still)}")
for h in still:
    print(f"  - {h}")
print(f"Wrote {p}")
PY
