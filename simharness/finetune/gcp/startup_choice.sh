#!/bin/bash
# CHOICE-FT-1 job for a GPU VM (launch with launch.sh and FT_STARTUP pointing here): trains the yes/no backing scorer
# (choice_lora.py), scores the eval person-days with the untuned model and at each snapshot, uploads each result as
# soon as it exists (so the run-time cap never loses a finished point), then removes the VM.
# Metadata: ft_prefix (code/choice_lora.py, data/train.jsonl, data/eval.jsonl), ft_model, ft_tag, ft_rows, ft_eval_at;
# score-only: ft_adapter_gcs (an adapter folder) and ft_eval_file (one or more space-separated files under data/).
set -uo pipefail
md() { curl -sf -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
PREFIX=$(md ft_prefix); MODEL=$(md ft_model); TAG=$(md ft_tag)
ROWS=$(md ft_rows || echo 0); EVAL_AT=$(md ft_eval_at || echo "")
ADAPTER_GCS=$(md ft_adapter_gcs || echo "")   # set: score data/$EVAL_FILE with this adapter, no training
EVAL_FILE=$(md ft_eval_file || echo eval.jsonl)
WORK=/opt/ft; mkdir -p $WORK; cd $WORK
[ -f STARTED ] && exit 0   # a reboot must not run the job again
touch STARTED
LOG=$WORK/job.log; RUN=$PREFIX/runs/$TAG
( while true; do gsutil -q cp $LOG $RUN/job.log 2>/dev/null; sleep 60; done ) &

job() {
  set -e
  echo "job start $(date -u +%FT%TZ)"; echo "model=$MODEL rows=$ROWS eval_at=$EVAL_AT"
  for i in $(seq 1 60); do nvidia-smi >/dev/null 2>&1 && break; echo "waiting for the GPU driver ($i)"; sleep 10; done
  nvidia-smi
  PY=""
  for c in /opt/conda/bin/python3 /opt/python/*/bin/python3 /usr/bin/python3; do
    if [ -x "$c" ] && "$c" -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then PY=$c; break; fi
  done
  [ -n "$PY" ] || { echo "no python with CUDA torch"; exit 1; }
  TORCH=$($PY -c "import torch; print(torch.__version__.split('+')[0])")
  $PY -m pip uninstall -q -y torchaudio || true
  # the versions the packing was checked against locally (transformers 5.20.2, peft 0.21.3: the newest on the image's Python 3.10)
  $PY -m pip install -q "transformers==5.20.2" "peft==0.21.3" accelerate "jinja2>=3.1" "torch==$TORCH" \
    || $PY -m pip install -q --break-system-packages "transformers==5.20.2" "peft==0.21.3" accelerate "jinja2>=3.1" "torch==$TORCH"
  $PY -c "import torch, transformers, peft; print(torch.__version__, transformers.__version__, peft.__version__, torch.cuda.get_device_name(0))"
  if [ -n "$ADAPTER_GCS" ]; then
    gsutil -q cp $PREFIX/code/choice_lora.py .
    mkdir -p adapter && gsutil -q -m cp -r "$ADAPTER_GCS/*" adapter/
    for E in $EVAL_FILE; do  # several files: each is scored and uploaded on its own (a preemption keeps the rest)
      gsutil -q cp $PREFIX/data/$E .
      echo "score $E start $(date -u +%s)"
      $PY choice_lora.py score --model "$MODEL" --adapter adapter --eval "$E" --out "scores_$E"
      echo "score $E end $(date -u +%s)"
      gsutil -q cp "scores_$E" $RUN/
    done
    echo "job end $(date -u +%FT%TZ)"; return 0
  fi
  gsutil -q cp $PREFIX/code/choice_lora.py $PREFIX/data/train.jsonl $PREFIX/data/eval.jsonl .
  $PY choice_lora.py train --model "$MODEL" --train train.jsonl --eval eval.jsonl --out adapter --rows "$ROWS" \
    --eval-at $EVAL_AT --grad-checkpoint --score-base --upload "$RUN"
  echo "job end $(date -u +%FT%TZ)"
}

( job ) >> $LOG 2>&1
if [ $? -eq 0 ]; then echo ok > STATUS; else echo failed > STATUS; fi
gsutil -q cp $LOG $RUN/job.log; gsutil -q cp STATUS $RUN/STATUS
NAME=$(curl -sf -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/name)
ZONE=$(curl -sf -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/zone | awk -F/ '{print $NF}')
gcloud compute instances delete "$NAME" --zone "$ZONE" --quiet || systemctl poweroff
