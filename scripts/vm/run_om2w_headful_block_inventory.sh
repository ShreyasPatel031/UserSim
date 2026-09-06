#!/usr/bin/env bash
# Full OM2W unique-host BLOCKED inventory with headed Chromium (+Xvfb).
# No LLM — preflight only. Parallel on one e2-standard-8 (or override MACHINE/WORKERS).
#
#   ./scripts/vm/run_om2w_headful_block_inventory.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}"
ZONE="${GCP_ZONE:-us-central1-b}"
MACHINE="${GCP_MACHINE:-e2-standard-8}"
NAME="${VM_NAME:-usersim-om2w-hf-block-$(date +%y%m%d-%H%M%S)}"
WORKERS="${WORKERS:-12}"
TAG="${TAG:-headful_full_$(date +%H%M)}"
KEEP_VM="${KEEP_VM:-0}"
GCS_PREFIX="${GCS_PREFIX:-gs://usersim-bakeoff-347838016394}"
SSH=(gcloud compute ssh "$NAME" --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap)
SCP=(gcloud compute scp --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap)

echo "Creating $NAME ($MACHINE) workers=$WORKERS — headful Chromium BLOCK inventory (no LLM)..."
gcloud compute instances create "$NAME" \
  --project="$PROJECT" --zone="$ZONE" \
  --machine-type="$MACHINE" \
  --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
  --boot-disk-size=40GB --boot-disk-type=pd-balanced \
  --network=main-vpc --subnet=primary-subnet \
  --scopes=cloud-platform --tags=allow-iap-ssh --quiet

cleanup() {
  if [[ "$KEEP_VM" == "0" ]]; then
    echo "Deleting $NAME..."
    gcloud compute instances delete "$NAME" --project="$PROJECT" --zone="$ZONE" --quiet || true
  fi
}
trap cleanup EXIT

echo "Waiting for SSH..."
for _ in $(seq 1 40); do
  "${SSH[@]}" --command="echo up" --quiet 2>/dev/null && break
  sleep 5
done

"${SSH[@]}" --command="mkdir -p ~/usersim/data/om2w ~/usersim/results/capability ~/usersim/secrets"
"${SCP[@]}" --recurse "$ROOT/src" "$NAME:~/usersim/" --quiet
"${SCP[@]}" "$ROOT/data/om2w/om2w_tasks.json" "$NAME:~/usersim/data/om2w/" --quiet
"${SCP[@]}" "$ROOT/data/om2w/online_mind2web.jsonl" "$NAME:~/usersim/data/om2w/" --quiet

"${SSH[@]}" --command="bash -s" <<REMOTE
set -euo pipefail
cd ~/usersim
sudo apt-get update -qq
# Minimal apt — Playwright --with-deps pulls Chromium system libs.
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip xvfb || \
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --fix-missing python3-venv python3-pip xvfb
python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q playwright
.venv/bin/playwright install --with-deps chromium
export DISPLAY=:99
Xvfb :99 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 &
sleep 1
PYTHONUNBUFFERED=1 PYTHONPATH=src .venv/bin/python -m capability.run_om2w_unblock_bakeoff \
  --backends chromium_headful \
  --workers ${WORKERS} \
  --tag ${TAG}
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
s = d["summary"]["chromium_headful"]
# Map to task counts: each OM2W task inherits host block status
tasks = json.loads(Path("data/om2w/om2w_tasks.json").read_text())["tasks"]
blocked_hosts = set(s["blocked_hosts"])
ok_hosts = set()
for r in d["rows"]:
    if not r["blocked"]:
        ok_hosts.add(r["host"])
n_tasks = len(tasks)
n_blocked_tasks = sum(1 for t in tasks if t.get("website_host") in blocked_hosts)
n_ok_tasks = n_tasks - n_blocked_tasks
print("=== OM2W headful Chromium BLOCK inventory (no LLM) ===")
print(f"unique hosts: {s['n']}  OK={s['ok']} ({s['ok_rate']:.1%})  BLOCKED={s['blocked']}")
print(f"tasks (300):  OK≈{n_ok_tasks}  BLOCKED≈{n_blocked_tasks} ({n_blocked_tasks/n_tasks:.1%})")
print("blocked hosts:")
for h in s["blocked_hosts"]:
    print(f"  - {h}")
print(f"Wrote {p}")
PY
