#!/bin/bash
set -euo pipefail
sudo systemctl stop usersim-floor-befm.service || true
# Do not pkill -f a string that appears in THIS command line.
pkill -f 'python3 -m vllm.entrypoints' || true
pkill -f 'python3 -u /opt/usersim_fm/scripts/colab_qwen3_8b_floor_befm.py' || true
sleep 2
sudo mkdir -p /opt/usersim_fm/scripts /opt/usersim_fm
sudo cp /tmp/usersim_floor_scripts/*.py /opt/usersim_fm/scripts/
sudo cp /tmp/usersim_floor_scripts/run_qwen_befm_full.sh /opt/usersim_fm/scripts/
sudo cp /tmp/usersim_floor_scripts/watch_qwen_befm_floor.sh /opt/usersim_fm/scripts/
sudo cp /tmp/usersim_floor_scripts/usersim-floor-befm.service /opt/usersim_fm/scripts/
sudo cp /opt/usersim_fm/scripts/usersim-floor-befm.service /etc/systemd/system/
sudo chmod +x /opt/usersim_fm/scripts/*.sh
sudo touch /opt/usersim_fm/WATCHDOG_ARMED
sudo chmod 666 /opt/usersim_fm/WATCHDOG_ARMED
sudo systemctl daemon-reload
sudo systemctl enable usersim-floor-befm.service
sudo systemctl restart usersim-floor-befm.service
echo DEPLOY_OK
sudo systemctl is-active usersim-floor-befm.service
ls -la /opt/usersim_fm/scripts/protocol.py /opt/usersim_fm/WATCHDOG_ARMED
