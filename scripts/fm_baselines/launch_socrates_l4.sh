#!/usr/bin/env bash
# Create one Spot L4 (g2-standard-8) and start the full Socrates vLLM run.
# Usage: bash scripts/fm_baselines/launch_socrates_l4.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}"
ZONE="${ZONE:-us-central1-a}"
NAME="${VM_NAME:-fm-gate0-socrates-l4}"
NETWORK="${NETWORK:-main-vpc}"
SUBNET="${SUBNET:-primary-subnet}"
GCS_PREFIX="${GCS_PREFIX:-gs://usersim-bakeoff-347838016394/fm_baselines/socrates_vllm}"
HF_TOKEN="${HF_TOKEN:-}"
if [[ -z "$HF_TOKEN" && -f secrets/env ]]; then
  # shellcheck disable=SC1091
  set -a; source secrets/env; set +a
  HF_TOKEN="${HF_TOKEN:-${HUGGING_FACE_HUB_TOKEN:-}}"
fi
if [[ -z "$HF_TOKEN" && -f "$HOME/.cache/huggingface/token" ]]; then
  HF_TOKEN="$(cat "$HOME/.cache/huggingface/token")"
fi
: "${HF_TOKEN:?set HF_TOKEN or put it in secrets/env / ~/.cache/huggingface/token}"

export CLOUDSDK_CORE_PROJECT="$PROJECT"

if ! gcloud compute instances describe "$NAME" --zone="$ZONE" &>/dev/null; then
  echo "Creating Spot L4 $NAME in $ZONE..."
  gcloud compute instances create "$NAME" \
    --zone="$ZONE" \
    --machine-type=g2-standard-8 \
    --accelerator=count=1,type=nvidia-l4 \
    --provisioning-model=SPOT \
    --instance-termination-action=STOP \
    --maintenance-policy=TERMINATE \
    --boot-disk-size=200GB \
    --boot-disk-type=pd-balanced \
    --image-family=pytorch-2-9-cu129-ubuntu-2204-nvidia-580 \
    --image-project=deeplearning-platform-release \
    --network="$NETWORK" \
    --subnet="$SUBNET" \
    --tags=allow-iap-ssh,ssh-enabled \
    --scopes=cloud-platform \
    --metadata=install-nvidia-driver=True \
    --quiet
else
  echo "VM $NAME already exists"
  STATUS=$(gcloud compute instances describe "$NAME" --zone="$ZONE" --format='value(status)')
  if [[ "$STATUS" != "RUNNING" ]]; then
    gcloud compute instances start "$NAME" --zone="$ZONE" --quiet
  fi
fi

echo "Waiting for SSH..."
for i in $(seq 1 60); do
  if gcloud compute ssh "$NAME" --zone="$ZONE" --tunnel-through-iap --command='echo SSH_OK' &>/dev/null; then
    break
  fi
  sleep 10
done
gcloud compute ssh "$NAME" --zone="$ZONE" --tunnel-through-iap --command='echo SSH_OK'

# Bundle scripts + env
TAR=/tmp/socrates_vllm_bundle.tar
tar -cf "$TAR" \
  -C "$ROOT" \
  scripts/fm_baselines/socrates_metric.py \
  scripts/fm_baselines/socrates_vllm_shard.py \
  scripts/fm_baselines/socrates_merge_shards.py \
  scripts/fm_baselines/gate_contract.py \
  docs/plans/gates.yaml

gcloud compute scp --tunnel-through-iap --zone="$ZONE" "$TAR" "$NAME:/tmp/socrates_vllm_bundle.tar"
gcloud compute ssh "$NAME" --zone="$ZONE" --tunnel-through-iap --command="
set -euo pipefail
sudo mkdir -p /opt/usersim_fm/{scripts,results/socrates,logs,data}
sudo chown -R \$USER:\$USER /opt/usersim_fm
tar -xf /tmp/socrates_vllm_bundle.tar -C /tmp
cp /tmp/scripts/fm_baselines/*.py /opt/usersim_fm/scripts/
cp /tmp/docs/plans/gates.yaml /opt/usersim_fm/gates.yaml
mkdir -p /content && ln -sfn /opt/usersim_fm /content/fm_baselines

# GPU check
nvidia-smi -L || (echo 'waiting for GPU driver...' && sleep 30 && nvidia-smi -L)

python3 -m pip install -q -U pip
python3 -m pip install -q -U 'vllm>=0.6.0' transformers datasets huggingface_hub 'jinja2>=3.1.0' scipy numpy pyyaml accelerate

export HF_TOKEN='$HF_TOKEN'
export HUGGING_FACE_HUB_TOKEN='$HF_TOKEN'
python3 - <<'PY'
import os
from huggingface_hub import login
login(token=os.environ['HF_TOKEN'], add_to_git_credential=True)
print('hf_login_ok')
PY

# Single shard = whole run on this one L4
nohup env \
  SHARD_ID=0 NUM_SHARDS=1 \
  QUANT=fp8 \
  MAX_MODEL_LEN=4096 MAX_NEW_TOKENS=32 \
  MAX_NUM_SEQS=256 GPU_MEM_UTIL=0.92 \
  OUT_DIR=/opt/usersim_fm/results/socrates \
  GCS_DEST='$GCS_PREFIX' \
  GATES_CONTRACT=/opt/usersim_fm/gates.yaml \
  HF_TOKEN='$HF_TOKEN' HUGGING_FACE_HUB_TOKEN='$HF_TOKEN' \
  python3 -u /opt/usersim_fm/scripts/socrates_vllm_shard.py \
  > /opt/usersim_fm/logs/socrates_vllm.log 2>&1 &
echo \$! > /opt/usersim_fm/results/socrates_vllm.pid
echo STARTED pid=\$(cat /opt/usersim_fm/results/socrates_vllm.pid)
sleep 3
tail -20 /opt/usersim_fm/logs/socrates_vllm.log || true
"

echo "Launched. Monitor with:"
echo "  gcloud compute ssh $NAME --zone=$ZONE --tunnel-through-iap --command='tail -f /opt/usersim_fm/logs/socrates_vllm.log'"
echo "GCS: $GCS_PREFIX"
