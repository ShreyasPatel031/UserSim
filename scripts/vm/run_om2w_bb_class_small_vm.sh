#!/usr/bin/env bash
# Small-VM bakeoff: real OSS Browserbase-class backends vs chromium_headless.
# Hosts = the 32 still blocked on headless (from prior merge), unless LIMIT_HOSTS set.
#
#   ./scripts/vm/run_om2w_bb_class_small_vm.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}"
ZONE="${GCP_ZONE:-us-central1-b}"
MACHINE="${GCP_MACHINE:-e2-medium}"   # small VM
NAME="${VM_NAME:-usersim-om2w-bb-$(date +%y%m%d-%H%M%S)}"
WORKERS="${WORKERS:-2}"
TAG="${TAG:-bb_class_$(date +%H%M)}"
BACKENDS="${BACKENDS:-chromium_headless,camoufox,steel,patchright}"
KEEP_VM="${KEEP_VM:-0}"
GCS_PREFIX="${GCS_PREFIX:-gs://usersim-bakeoff-347838016394}"
HOSTS_FILE="${HOSTS_FILE:-results/capability/om2w_unblock_merged.json}"
SSH=(gcloud compute ssh "$NAME" --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap)
SCP=(gcloud compute scp --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap)

[[ -f secrets/env ]] || { echo "ERROR: secrets/env missing"; exit 1; }
[[ -f "$HOSTS_FILE" ]] || { echo "ERROR: hosts file missing: $HOSTS_FILE"; exit 1; }

echo "Creating SMALL VM $NAME ($MACHINE) in $ZONE..."
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

"${SSH[@]}" --command="mkdir -p ~/usersim/secrets ~/usersim/results/capability ~/usersim/data/om2w"
"${SCP[@]}" --recurse "$ROOT/src" "$NAME:~/usersim/" --quiet
# Only OM2W task files — full data/ is ~200MB over IAP and stalls.
"${SCP[@]}" "$ROOT/data/om2w/om2w_tasks.json" "$NAME:~/usersim/data/om2w/" --quiet
"${SCP[@]}" "$ROOT/data/om2w/online_mind2web.jsonl" "$NAME:~/usersim/data/om2w/" --quiet
"${SCP[@]}" "$ROOT/secrets/env" "$NAME:~/usersim/secrets/env" --quiet
"${SCP[@]}" "$ROOT/$HOSTS_FILE" "$NAME:~/usersim/results/capability/om2w_unblock_merged.json" --quiet

"${SSH[@]}" --command="bash -s" <<REMOTE
set -euo pipefail
cd ~/usersim
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3-venv python3-pip xvfb libgtk-3-0 libx11-xcb1 libasound2 docker.io curl >/dev/null
sudo usermod -aG docker "\$USER" || true
sudo systemctl start docker

python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q 'camoufox[geoip]' patchright playwright

# Camoufox browser binary (required — previous run failed without this)
.venv/bin/python -m camoufox fetch

.venv/bin/playwright install --with-deps chromium
.venv/bin/python -m patchright install chromium || true

# Steel self-host (Browserbase-class OSS CDP)
sudo docker pull ghcr.io/steel-dev/steel-browser:latest
sudo docker rm -f steel-browser 2>/dev/null || true
sudo docker run -d --name steel-browser \
  -p 3000:3000 -p 9223:9223 \
  ghcr.io/steel-dev/steel-browser:latest
# wait for API
for i in \$(seq 1 30); do
  curl -sf http://127.0.0.1:3000/ >/dev/null 2>&1 && break || true
  curl -sf http://127.0.0.1:3000/v1/sessions >/dev/null 2>&1 && break || true
  sleep 2
done
curl -s http://127.0.0.1:3000/v1/sessions -X POST -H 'content-type: application/json' -d '{}' | head -c 400 || true
echo

export DISPLAY=:99
Xvfb :99 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 &
export STEEL_API_URL=http://127.0.0.1:3000

PYTHONPATH=src .venv/bin/python -m capability.run_om2w_unblock_bakeoff \
  --backends ${BACKENDS} \
  --hosts-file results/capability/om2w_unblock_merged.json \
  --workers ${WORKERS} \
  --tag ${TAG}
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
p = Path("results/capability/om2w_unblock_${TAG}.json")
d = json.loads(p.read_text())
base = d["summary"].get("chromium_headless", {})
print("BASELINE chromium_headless:", f"{base.get('ok',0)}/{base.get('n',0)} ok_rate={base.get('ok_rate')}")
print()
for name, s in sorted(d["summary"].items(), key=lambda kv: (-kv[1].get("n_rescued_vs_chromium_headless", 0), -kv[1].get("ok_rate", 0))):
    if name == "chromium_headless":
        continue
    print(f"{name:18} ok={s['ok']}/{s['n']} ({s['ok_rate']:.1%})  rescued={s.get('n_rescued_vs_chromium_headless',0)}  errors={s.get('backend_unavailable_or_error',0)}")
    for h in s.get("rescued_vs_chromium_headless") or []:
        print(f"  + {h}")
PY
