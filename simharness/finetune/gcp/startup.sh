#!/bin/bash
# Fine-tune job for a GPU VM: runs once at first boot, uploads everything to the bucket prefix, then removes the VM.
# Parameters come from instance metadata (see launch.sh). Outputs are private (weights, real and simulated text).
set -uo pipefail
md() { curl -sf -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
PREFIX=$(md ft_prefix); MODEL=$(md ft_model); TAG=$(md ft_tag)
EPOCHS=$(md ft_epochs || echo 1); BATCH=$(md ft_batch || echo 2); ACCUM=$(md ft_accum || echo 8)
GEN_BATCH=$(md ft_gen_batch || echo 8); GC=$(md ft_grad_checkpoint || echo 0); SKIP_BASE=$(md ft_skip_base || echo 0)
WORK=/opt/ft; mkdir -p $WORK; cd $WORK
[ -f STARTED ] && exit 0   # a reboot must not run the job again
touch STARTED
LOG=$WORK/job.log; RUN=$PREFIX/runs/$TAG
( while true; do gsutil -q cp $LOG $RUN/job.log 2>/dev/null; sleep 60; done ) &

job() {
  set -e
  date -u; echo "model=$MODEL epochs=$EPOCHS batch=$BATCH accum=$ACCUM gc=$GC"
  for i in $(seq 1 60); do nvidia-smi >/dev/null 2>&1 && break; echo "waiting for the GPU driver ($i)"; sleep 10; done
  nvidia-smi
  PY=""
  for c in /opt/conda/bin/python3 /opt/python/*/bin/python3 /usr/bin/python3; do
    if [ -x "$c" ] && "$c" -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then PY=$c; break; fi
  done
  if [ -z "$PY" ]; then python3 -m venv /opt/ftenv; /opt/ftenv/bin/pip install -q torch; PY=/opt/ftenv/bin/python; fi
  echo "python: $PY"; $PY -c "import torch; print(torch.__version__, torch.cuda.get_device_name(0))"
  # keep the image's torch build (pin it), and drop torchaudio: transformers imports it when present and the image's
  # copy can fail to load
  TORCH=$($PY -c "import torch; print(torch.__version__.split('+')[0])")
  $PY -m pip uninstall -q -y torchaudio || true
  $PY -m pip install -q --upgrade transformers peft accelerate "jinja2>=3.1" "torch==$TORCH" \
    || $PY -m pip install -q --upgrade --break-system-packages transformers peft accelerate "jinja2>=3.1" "torch==$TORCH"
  $PY -c "import torch, transformers, peft; print(torch.__version__, transformers.__version__, peft.__version__, torch.cuda.is_available())"
  gsutil -q cp $PREFIX/code/lora.py $PREFIX/data/train.jsonl $PREFIX/data/eval.jsonl .
  GCFLAG=""; [ "$GC" = "1" ] && GCFLAG="--grad-checkpoint"
  if [ "$SKIP_BASE" != "1" ]; then  # the untuned model's comments, for the paired comparison
    $PY lora.py generate --model "$MODEL" --rows eval.jsonl --out gen_base.jsonl --batch "$GEN_BATCH"
    gsutil -q cp gen_base.jsonl $RUN/
  fi
  $PY lora.py train --model "$MODEL" --train train.jsonl --out adapter --epochs "$EPOCHS" --batch "$BATCH" \
    --accum "$ACCUM" $GCFLAG
  $PY lora.py generate --model "$MODEL" --adapter adapter --rows eval.jsonl --out gen_tuned.jsonl --batch "$GEN_BATCH"
  gsutil -q -m cp -r gen_tuned.jsonl adapter $RUN/
  date -u
}

# not inside an `if`: bash ignores `set -e` in a condition, and a failed step must stop the job
( job ) >> $LOG 2>&1
if [ $? -eq 0 ]; then echo ok > STATUS; else echo failed > STATUS; fi
gsutil -q cp $LOG $RUN/job.log; gsutil -q cp STATUS $RUN/STATUS
# done: remove this machine (the launcher's run-time cap is the backstop if this fails)
NAME=$(curl -sf -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/name)
ZONE=$(curl -sf -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/zone | awk -F/ '{print $NF}')
gcloud compute instances delete "$NAME" --zone "$ZONE" --quiet || systemctl poweroff
