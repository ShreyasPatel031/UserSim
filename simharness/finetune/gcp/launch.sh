#!/bin/bash
# Launch one fine-tune job on a GPU VM that deletes itself when done and is deleted at the run-time cap anyway.
#   launch.sh TAG MODEL MACHINE ZONE MAX_HOURS [EPOCHS BATCH ACCUM GEN_BATCH GRAD_CHECKPOINT SKIP_BASE "SAVE_AT_ROWS"]
# Needs FT_PREFIX (gs://... holding code/lora.py, data/train.jsonl, data/eval.jsonl; results go to runs/TAG/).
# Optional FT_ADAPTER (gs://.../adapter of an earlier run): generate with it for data/eval.jsonl, no training.
# Optional FT_ACCELERATOR for machine types without a built-in GPU. Optional FT_NETWORK and FT_SUBNET when the project has no default network (the subnet must be in ZONE's region).
set -euo pipefail
TAG=$1; MODEL=$2; MACHINE=$3; ZONE=$4; HOURS=$5
EPOCHS=${6:-1}; BATCH=${7:-2}; ACCUM=${8:-8}; GEN_BATCH=${9:-8}; GC=${10:-0}; SKIP_BASE=${11:-0}; SAVE_AT=${12:-}
: "${FT_PREFIX:?set FT_PREFIX}"
HERE=$(cd "$(dirname "$0")" && pwd)
ACC=(); [ -n "${FT_ACCELERATOR:-}" ] && ACC=(--accelerator "$FT_ACCELERATOR")  # e.g. type=nvidia-tesla-t4,count=1 on N1
NET=(); [ -n "${FT_NETWORK:-}" ] && NET=(--network "$FT_NETWORK" --subnet "${FT_SUBNET:?set FT_SUBNET with FT_NETWORK}")
gcloud compute instances create "ft-$TAG" --zone "$ZONE" --machine-type "$MACHINE" \
  --maintenance-policy TERMINATE --provisioning-model STANDARD "${NET[@]}" "${ACC[@]}" \
  --max-run-duration "${HOURS}h" --instance-termination-action DELETE \
  --image-family pytorch-2-9-cu129-ubuntu-2204-nvidia-580 --image-project deeplearning-platform-release \
  --boot-disk-size 150GB --boot-disk-type pd-balanced --scopes cloud-platform \
  --labels purpose=simharness-finetune \
  --metadata-from-file startup-script="$HERE/startup.sh" \
  --metadata "install-nvidia-driver=True,ft_prefix=$FT_PREFIX,ft_model=$MODEL,ft_tag=$TAG,ft_epochs=$EPOCHS,ft_batch=$BATCH,ft_accum=$ACCUM,ft_gen_batch=$GEN_BATCH,ft_grad_checkpoint=$GC,ft_skip_base=$SKIP_BASE,ft_save_at=$SAVE_AT,ft_adapter_gcs=${FT_ADAPTER:-}"
