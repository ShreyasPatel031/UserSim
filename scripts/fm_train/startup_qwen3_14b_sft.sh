#!/bin/bash
# Startup script for Qwen3-14B QLoRA SFT training
# This script runs the full training pipeline on a Spot g2-standard-8 + 1x L4

set -euo pipefail

ROOT=/opt/usersim_fm
RESULTS=$ROOT/results/qwen3_14b_sft
ADAPTERS=$ROOT/adapters/qwen3_14b_sft
GCS_BUCKET=gs://ai-studio-bucket-347838016394-us-east1/usersim-models/qwen3_14b_sft
SCREEN_STUDIES="326nv,3muqx,3pcdm,3rvgz,53kjy"

mkdir -p $RESULTS $ADAPTERS
exec >> $RESULTS/boot.log 2>&1
echo "BOOT $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Wait for GPU
for i in $(seq 1 60); do
    nvidia-smi >/dev/null 2>&1 && break
    sleep 2
done

# Setup training venv (separate from vLLM to avoid transformers conflicts)
TRAIN_VENV=$ROOT/venvs/train_qwen3_14b
if [ ! -d "$TRAIN_VENV" ]; then
    echo "Creating training venv..."
    python3 -m venv $TRAIN_VENV
    source $TRAIN_VENV/bin/activate
    pip install --upgrade pip
    pip install torch==2.5.1+cu124 --index-url https://download.pytorch.org/whl/cu124
    pip install transformers==4.47.0 datasets accelerate peft bitsandbytes scipy
    pip install huggingface_hub
else
    source $TRAIN_VENV/bin/activate
fi

# Check if training is already done
if [ -f "$RESULTS/TRAIN_DONE.json" ]; then
    echo "TRAIN_DONE exists; exiting"
    exit 0
fi

# Function to update instance label
update_label() {
    local key=$1
    local value=$2
    python3 - "$key" "$value" <<'PY' || true
import sys, json, urllib.request
key, value = sys.argv[1], sys.argv[2]
def meta(path):
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/" + path,
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read().decode()
try:
    token = json.loads(meta("instance/service-accounts/default/token"))["access_token"]
    project = meta("project/project-id")
    zone = meta("instance/zone").rsplit("/", 1)[-1]
    name = meta("instance/name")
    url = f"https://compute.googleapis.com/compute/v1/projects/{project}/zones/{zone}/instances/{name}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        inst = json.loads(resp.read().decode())
    labels = dict(inst.get("labels") or {})
    labels[key] = value
    body = json.dumps({"labels": labels, "labelFingerprint": inst["labelFingerprint"]}).encode()
    post = urllib.request.Request(url + "/setLabels", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(post, timeout=20) as resp:
        resp.read()
    print(f"{key}={value}")
except Exception as e:
    print(f"label_update_failed: {e}")
PY
}

# Run training in background with checkpoint callback
run_training() {
    echo "Starting training at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    cd /opt/usersim_fm/scripts/fm_train
    
    export ROOT=$ROOT
    export RESULTS_SUBDIR=qwen3_14b_sft
    export SFT_CORPUS=$ROOT/data/socrates_sft.jsonl
    export SFT_MODEL=Qwen/Qwen3-14B
    export SFT_OUT=$ADAPTERS
    export MAX_SEQ=768
    export LR=1e-4
    export MICRO_BATCH=4
    export GRAD_ACCUM=8
    export LORA_R=16
    export MAX_STEPS=600
    export SAVE_STEPS=20
    export LOG_STEPS=5
    export RESUME=1
    export GCS_BUCKET=$GCS_BUCKET
    
    python3 -u sft_qwen3_14b_qlora.py >> $RESULTS/train.log 2>&1
    echo $? > $RESULTS/train.exit_code
}

# Anti-collapse sanity check at step 20
sanity_check_step20() {
    echo "Running anti-collapse sanity check..."
    CKPT=$ADAPTERS/checkpoint-20
    if [ ! -d "$CKPT" ]; then
        echo "checkpoint-20 not found; skipping sanity check"
        return 0
    fi
    
    python3 - "$CKPT" <<'PY'
import json, re, sys
from pathlib import Path
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

CKPT = sys.argv[1]
ROOT = Path("/opt/usersim_fm")
SYSTEM = "You are a participant in a survey experiment. Answer with a single number only when a numeric response is required."

# Load a few prompts
prompts = []
with open(ROOT / "data" / "socrates_sft.jsonl") as f:
    for i, line in enumerate(f):
        if i >= 50:
            break
        prompts.append(json.loads(line))

tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-14B", trust_remote_code=True)
quant = BitsAndBytesConfig(
    load_in_4bit=True, bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16,
)
base = AutoModelForCausalLM.from_pretrained(
    "Qwen/Qwen3-14B", quantization_config=quant, torch_dtype=torch.bfloat16,
    device_map={"": 0}, trust_remote_code=True,
)
model = PeftModel.from_pretrained(base, CKPT)
model.eval()

bare_num = re.compile(r"^\s*\d+(?:\.\d+)?\s*$")
bare_count = 0
total = 0

with torch.no_grad():
    for row in prompts:
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": row["prompt"]}]
        prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        inputs = tok(prompt, return_tensors="pt", truncation=True, max_length=512)
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
        outputs = model.generate(**inputs, max_new_tokens=16, do_sample=False, pad_token_id=tok.pad_token_id)
        gen = tok.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        total += 1
        if bare_num.match(gen.strip()):
            bare_count += 1

rate = bare_count / total if total > 0 else 0
print(f"SANITY_CHECK bare_rate={rate:.1%} ({bare_count}/{total})")
Path("/opt/usersim_fm/results/qwen3_14b_sft/SANITY_STEP20.json").write_text(
    json.dumps({"bare_count": bare_count, "total": total, "rate": rate}, indent=2) + "\n"
)
if rate < 0.95:
    print(f"SANITY_FAIL: bare_rate {rate:.1%} < 95%")
    sys.exit(1)
print("SANITY_PASS")
PY
    return $?
}

# Run screen evaluation at a checkpoint step
run_screen() {
    local step=$1
    echo "Running screen at step $step at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    
    CKPT=$ADAPTERS/checkpoint-$step
    if [ ! -d "$CKPT" ]; then
        echo "checkpoint-$step not found; skipping screen"
        return 0
    fi
    
    # Set gate state to running so watchdog doesn't interfere
    update_label "usersim-gate-state" "running"
    
    # Setup eval venv if needed
    EVAL_VENV=$ROOT/venvs/eval
    if [ ! -d "$EVAL_VENV" ]; then
        echo "Creating eval venv..."
        python3 -m venv $EVAL_VENV
        source $EVAL_VENV/bin/activate
        pip install --upgrade pip
        pip install torch==2.5.1+cu124 --index-url https://download.pytorch.org/whl/cu124
        pip install vllm==0.6.4.post1 transformers datasets huggingface_hub scipy numpy
    else
        source $EVAL_VENV/bin/activate
    fi
    
    SCREEN_DIR=$ROOT/results/qwen3_14b_sft/screens/step$step
    mkdir -p $SCREEN_DIR
    
    export RESULTS_DIR=$SCREEN_DIR
    export PROBE_MODEL=Qwen/Qwen3-14B-FP8
    export LORA_PATH=$CKPT
    export SMOKE_STUDIES=5
    export TEMPERATURE=0.6
    export TOP_P=0.9
    
    cd /opt/usersim_fm/scripts/fm_baselines
    python3 -u probe_qwen3_14b_acc.py >> $SCREEN_DIR/probe.log 2>&1
    
    # Upload results to GCS
    gsutil -m cp -r $SCREEN_DIR/* $GCS_BUCKET/screens/step$step/ || true
    
    # Check pass bar: W <= 0.160, clipped >= 70.0%, raw >= 66.0%
    python3 - "$SCREEN_DIR" <<'PY'
import json, sys
from pathlib import Path
screen_dir = Path(sys.argv[1])
summary = json.loads((screen_dir / "SUMMARY.json").read_text())
W = summary.get("wasserstein_mean")
acc_raw = summary.get("accuracy_raw")
acc_clip = summary.get("accuracy_clipped")
passed = True
checks = {}
checks["W <= 0.160"] = W is not None and W <= 0.160
checks["acc_raw >= 66.0%"] = acc_raw is not None and acc_raw >= 0.66
checks["acc_clipped >= 70.0%"] = acc_clip is not None and acc_clip >= 0.70
for check, ok in checks.items():
    status = "PASS" if ok else "FAIL"
    print(f"  {status}: {check}")
    if not ok:
        passed = False
overall = "PASS" if passed else "FAIL"
print(f"SCREEN_OVERALL: {overall}")
(screen_dir / "GATE.json").write_text(json.dumps({
    "W": W, "acc_raw": acc_raw, "acc_clipped": acc_clip,
    "checks": checks, "passed": passed
}, indent=2) + "\n")
PY
    
    update_label "usersim-gate-state" "done"
    source $TRAIN_VENV/bin/activate
}

# Main execution
echo "Starting main execution..."

# Check for early stop condition
early_stop_check() {
    if [ -f "$RESULTS/screens/step200/GATE.json" ]; then
        python3 - <<'PY'
import json, sys
from pathlib import Path
gate = json.loads(Path("/opt/usersim_fm/results/qwen3_14b_sft/screens/step200/GATE.json").read_text())
W = gate.get("W")
acc_clip = gate.get("acc_clipped")
if W is not None and W > 0.20:
    print(f"EARLY_STOP: W={W:.3f} > 0.20")
    sys.exit(1)
if acc_clip is not None and acc_clip < 0.65:
    print(f"EARLY_STOP: acc_clipped={acc_clip:.1%} < 65%")
    sys.exit(1)
print("Step 200 passes early stop check")
PY
        return $?
    fi
    return 0
}

# Monitor training and run screens at checkpoints
monitor_and_screen() {
    local last_screen=0
    while true; do
        if [ -f "$RESULTS/TRAIN_DONE.json" ] || [ -f "$RESULTS/train.exit_code" ]; then
            echo "Training completed or exited"
            break
        fi
        
        # Check for new checkpoints
        for step in 20 200 400 600; do
            CKPT=$ADAPTERS/checkpoint-$step
            if [ -d "$CKPT" ] && [ $step -gt $last_screen ]; then
                if [ $step -eq 20 ]; then
                    sanity_check_step20
                    if [ $? -ne 0 ]; then
                        echo "SANITY_FAIL at step 20; halting training"
                        update_label "usersim-train-state" "done"
                        update_label "usersim-do-not-start" "true"
                        pkill -f sft_qwen3_14b_qlora.py || true
                        exit 1
                    fi
                fi
                if [ $step -ge 200 ]; then
                    run_screen $step
                    if [ $step -eq 200 ]; then
                        early_stop_check
                        if [ $? -ne 0 ]; then
                            echo "EARLY_STOP triggered at step 200"
                            update_label "usersim-train-state" "done"
                            update_label "usersim-do-not-start" "true"
                            pkill -f sft_qwen3_14b_qlora.py || true
                            exit 1
                        fi
                    fi
                fi
                last_screen=$step
            fi
        done
        
        sleep 60
    done
}

# Start training in background
run_training &
TRAIN_PID=$!
echo "Training PID: $TRAIN_PID"
echo $TRAIN_PID > $RESULTS/train.pid

# Monitor and run screens
monitor_and_screen

# Wait for training to complete
wait $TRAIN_PID || true

# Final screen at step 600 if not already done
if [ -d "$ADAPTERS/checkpoint-600" ] && [ ! -f "$RESULTS/screens/step600/SUMMARY.json" ]; then
    run_screen 600
fi

# Cleanup
update_label "usersim-train-state" "done"
update_label "usersim-do-not-start" "true"
echo "COMPLETE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
