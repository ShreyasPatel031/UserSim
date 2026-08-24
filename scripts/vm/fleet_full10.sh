#!/usr/bin/env bash
# Launch full10 on N GCP Spot VMs — all tasks in parallel, max workers per VM.
#
# Default: 3 VMs × 4 workers = 12 slots, 10 tasks start simultaneously (4+3+3).
# Wall time ≈ slowest single task (~8–12 min), not serial waves.
#
# Usage:
#   ./scripts/vm/fleet_full10.sh
#   NUM_SHARDS=3 WORKERS=4 ./scripts/vm/fleet_full10.sh
#   ./scripts/vm/fleet_full10.sh --merge
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}"
ZONE="${GCP_ZONE:-us-central1-a}"
MACHINE="${GCP_MACHINE:-e2-standard-2}"
NUM_SHARDS="${NUM_SHARDS:-3}"
WORKERS="${WORKERS:-4}"
MODEL="${MISTRAL_MODEL:-mistral-small-2603}"
PREFIX="${FLEET_PREFIX:-usersim-bu-f10}"
TAG="mistral-small-2603_m33_stage1_fleet"

if [[ ! -f secrets/env ]]; then
  echo "ERROR: secrets/env missing"
  exit 1
fi

merge_shards() {
  PYTHONPATH=src python3 - <<'PY'
import json
from pathlib import Path
from capability.metrics import sort_runs, summarize

out_dir = Path("results/capability")
shards = sorted(out_dir.glob("full10_mistral_*_fleet_shard*.json"))
if not shards:
    raise SystemExit("No shard files found")
runs = []
for p in shards:
    runs.extend(json.loads(p.read_text()).get("runs") or [])
merged = out_dir / "full10_mistral_mistral-small-2603_m33_stage1.json"
base = json.loads(shards[0].read_text())
base.update(summarize(runs))
base["runs"] = sort_runs(runs)
base["fleet_shards"] = [p.name for p in shards]
merged.write_text(json.dumps(base, indent=2, default=str))
print(f"Merged {len(shards)} shards -> {merged.name} ({len(runs)} runs)")
PY
}

if [[ "${1:-}" == "--merge" ]]; then
  merge_shards
  exit 0
fi

gcloud config set account shreyas.patel@searce.com 2>/dev/null || true

echo "==> Fleet: ${NUM_SHARDS}× ${MACHINE} @ workers=${WORKERS} (parallel full10)"

TARBALL="/tmp/usersim-fleet-$$.tgz"
tar czf "$TARBALL" -C "$ROOT" src data requirements.txt secrets/env

for i in $(seq 0 $((NUM_SHARDS - 1))); do
  name="${PREFIX}-${i}"
  if ! gcloud compute instances describe "$name" --zone="$ZONE" --project="$PROJECT" &>/dev/null; then
    echo "    Creating ${name}..."
    gcloud compute instances create "$name" \
      --project="$PROJECT" --zone="$ZONE" \
      --machine-type="$MACHINE" \
      --provisioning-model=SPOT \
      --instance-termination-action=STOP \
      --boot-disk-size=30GB --boot-disk-type=pd-balanced \
      --network=main-vpc --subnet=primary-subnet \
      --scopes=cloud-platform \
      --tags=allow-iap-ssh \
      --quiet
  else
    gcloud compute instances start "$name" --zone="$ZONE" --project="$PROJECT" --quiet 2>/dev/null || true
  fi
done

run_shard() {
  local i="$1"
  local name="${PREFIX}-${i}"
  echo "    Shard ${i} -> ${name}"
  gcloud compute scp "$TARBALL" "${name}:~/usersim.tgz" \
    --zone="$ZONE" --project="$PROJECT" --tunnel-through-iap --quiet
  gcloud compute ssh "$name" --zone="$ZONE" --project="$PROJECT" --tunnel-through-iap --quiet \
    --command="set -euxo pipefail
rm -rf ~/usersim && mkdir -p ~/usersim
tar xzf ~/usersim.tgz -C ~/usersim
cd ~/usersim
if [[ ! -d .venv ]]; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip
  python3 -m venv .venv
  .venv/bin/pip install -q -U pip wheel
  .venv/bin/pip install -q -r requirements.txt
  .venv/bin/playwright install chromium
  sudo .venv/bin/playwright install-deps chromium
fi
export BROWSER_USE_FAST=1
set -a && source secrets/env && set +a
nohup env PYTHONPATH=src .venv/bin/python -m capability.run_mistral_bakeoff \
  --stage full10 --model ${MODEL} --workers ${WORKERS} --no-preflight \
  --num-shards ${NUM_SHARDS} --shard-id ${i} \
  --tag ${TAG}_shard${i} \
  > ~/bakeoff_shard${i}.log 2>&1 &
echo STARTED_SHARD_${i}
"
}

for i in $(seq 0 $((NUM_SHARDS - 1))); do
  run_shard "$i" &
done
wait
rm -f "$TARBALL"

echo ""
echo "==> All shards launched in background on VMs."
echo "    Wall time target: ~8–12 min (all 10 tasks parallel)"
echo "    Monitor:  gcloud compute ssh ${PREFIX}-0 --zone=${ZONE} --tunnel-through-iap -- tail -f ~/bakeoff_shard0.log"
echo "    Pull+merge: ./scripts/vm/fleet_full10.sh --pull && ./scripts/vm/fleet_full10.sh --merge"

if [[ "${1:-}" == "--pull" ]] || [[ "${1:-}" == "--wait" ]]; then
  echo "==> Waiting 12 min then pulling results..."
  sleep 720
  for i in $(seq 0 $((NUM_SHARDS - 1))); do
    gcloud compute scp "${PREFIX}-${i}:~/usersim/results/capability/full10_mistral_${TAG}_shard${i}.json" \
      results/capability/ --zone="$ZONE" --project="$PROJECT" --tunnel-through-iap --quiet || true
  done
  merge_shards
fi
