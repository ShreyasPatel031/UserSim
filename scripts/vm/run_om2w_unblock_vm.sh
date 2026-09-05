#!/usr/bin/env bash
# One-shot GCP VM: OM2W OSS unblock bakeoff (no LLM). Compares chromium / camoufox / patchright.
#
# Usage:
#   ./scripts/vm/run_om2w_unblock_vm.sh
#   LIMIT_HOSTS=20 ./scripts/vm/run_om2w_unblock_vm.sh   # smoke
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}"
ZONE="${GCP_ZONE:-us-central1-b}"
MACHINE="${GCP_MACHINE:-e2-standard-8}"
NAME="${VM_NAME:-usersim-om2w-unblock-$(date +%y%m%d-%H%M%S)}"
WORKERS="${WORKERS:-8}"
LIMIT_HOSTS="${LIMIT_HOSTS:-}"
TAG="${TAG:-oss_parallel}"
BACKENDS="${BACKENDS:-chromium_headless,chromium_headful,camoufox,patchright}"
KEEP_VM="${KEEP_VM:-0}"
GCS_PREFIX="${GCS_PREFIX:-gs://usersim-bakeoff-347838016394}"
SSH=(gcloud compute ssh "$NAME" --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap)
SCP=(gcloud compute scp --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap)

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
  --boot-disk-size=50GB \
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

"${SSH[@]}" --command="mkdir -p ~/usersim/secrets ~/usersim/results/capability"
"${SCP[@]}" --recurse "$ROOT/src" "$NAME:~/usersim/" --quiet
"${SCP[@]}" --recurse "$ROOT/data" "$NAME:~/usersim/" --quiet
"${SCP[@]}" "$ROOT/secrets/env" "$NAME:~/usersim/secrets/env" --quiet

REMOTE_LIMIT_ARGS=()
[[ -n "$LIMIT_HOSTS" ]] && REMOTE_LIMIT_ARGS=(--limit-hosts "$LIMIT_HOSTS")

"${SSH[@]}" --command="bash -s" <<REMOTE
set -euo pipefail
cd ~/usersim
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip xvfb libgtk-3-0 libx11-xcb1 libasound2 >/dev/null
python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q playwright patchright camoufox
.venv/bin/playwright install --with-deps chromium
.venv/bin/python -m patchright install chromium || true
export DISPLAY=:99
Xvfb :99 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 &
sleep 1
mkdir -p results/capability
PYTHONPATH=src .venv/bin/python -m capability.run_om2w_unblock_bakeoff \
  --backends ${BACKENDS} \
  --workers ${WORKERS} --tag ${TAG} ${REMOTE_LIMIT_ARGS[@]+"${REMOTE_LIMIT_ARGS[@]}"}
REMOTE

"${SCP[@]}" \
  "$NAME:~/usersim/results/capability/om2w_unblock_${TAG}.json" \
  "$ROOT/results/capability/om2w_unblock_${TAG}.json" --quiet

gcloud storage cp "$ROOT/results/capability/om2w_unblock_${TAG}.json" \
  "${GCS_PREFIX}/om2w_unblock/om2w_unblock_${TAG}.json" --quiet || true

echo "DONE -> results/capability/om2w_unblock_${TAG}.json"
python3 - <<PY
import json
from pathlib import Path
p=Path("results/capability/om2w_unblock_${TAG}.json")
d=json.loads(p.read_text())
print(json.dumps(d["summary"], indent=2))
best=max(d["summary"].items(), key=lambda kv: kv[1].get("ok_rate",0))
print("best_backend", best[0], best[1])
PY
