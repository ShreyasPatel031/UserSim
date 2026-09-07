#!/usr/bin/env bash
set -euo pipefail
sudo mkdir -p /opt/usersim_fm/{scripts,data,results,logs,hf_home}
sudo cp /tmp/usersim_psych101_scripts/*.py /opt/usersim_fm/scripts/
sudo cp /tmp/usersim_psych101_scripts/run_qwen_psych101_full.sh /opt/usersim_fm/scripts/
sudo cp /tmp/usersim_psych101_scripts/usersim-floor-psych101.service /opt/usersim_fm/scripts/
sudo cp /opt/usersim_fm/scripts/usersim-floor-psych101.service /etc/systemd/system/
sudo chmod +x /opt/usersim_fm/scripts/*.sh
# optional HF token file
if [[ -f /tmp/usersim_psych101_scripts/hf_token ]]; then
  sudo mkdir -p /root/.cache/huggingface
  sudo cp /tmp/usersim_psych101_scripts/hf_token /root/.cache/huggingface/token
  sudo chmod 600 /root/.cache/huggingface/token
fi
# shard env overrides via drop-in
SHARD_ID="${SHARD_ID:-0}"
NUM_SHARDS="${NUM_SHARDS:-1}"
BATCH_SIZE="${BATCH_SIZE:-4}"
sudo mkdir -p /etc/systemd/system/usersim-floor-psych101.service.d
sudo tee /etc/systemd/system/usersim-floor-psych101.service.d/override.conf >/dev/null <<EOF
[Service]
Environment=SHARD_ID=${SHARD_ID}
Environment=NUM_SHARDS=${NUM_SHARDS}
Environment=BATCH_SIZE=${BATCH_SIZE}
EOF
sudo touch /opt/usersim_fm/WATCHDOG_ARMED
sudo chmod 666 /opt/usersim_fm/WATCHDOG_ARMED
sudo systemctl daemon-reload
sudo systemctl enable usersim-floor-psych101.service
sudo systemctl restart usersim-floor-psych101.service
echo DEPLOY_OK shard=${SHARD_ID}/${NUM_SHARDS} batch=${BATCH_SIZE}
sudo systemctl is-active usersim-floor-psych101.service
