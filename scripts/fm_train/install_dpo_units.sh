#!/bin/bash
# Install / refresh Socrates DPO systemd units on the SFT L4 VM.
# Idempotent. Called by deploy and by instance startup-script.
set -euo pipefail
ROOT=/opt/usersim_fm
mkdir -p "$ROOT/results" "$ROOT/adapters" "$ROOT/data"

cat > /etc/systemd/system/usersim-dpo-socrates.service <<'EOF'
[Unit]
Description=UserSim Socrates QLoRA DPO from ckpt-425
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
Environment=ROOT=/opt/usersim_fm
Environment=SFT_MODEL=Qwen/Qwen3-8B-Base
Environment=SFT_ADAPTER=/opt/usersim_fm/adapters/socrates_qwen3_8b_qlora/checkpoint-425
Environment=TRAIN_PY=/opt/usersim_fm/venvs/train/bin/python3
Environment=RESUME=1
Environment=LR=1e-6
Environment=MICRO_BATCH=1
Environment=GRAD_ACCUM=64
Environment=SAVE_STEPS=25
Environment=EPOCHS=1
Environment=PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
Environment=PYTHONPATH=/opt/usersim_fm/scripts/fm_train
WorkingDirectory=/opt/usersim_fm
ExecStart=/usr/bin/python3 -u /opt/usersim_fm/scripts/fm_train/boot_socrates_dpo.py
Restart=on-failure
RestartSec=60
Nice=5
StandardOutput=append:/opt/usersim_fm/results/socrates_dpo.log
StandardError=append:/opt/usersim_fm/results/socrates_dpo.log

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/usersim-dpo-watchdog.service <<'EOF'
[Unit]
Description=UserSim Socrates DPO watchdog (one poll)
After=network-online.target

[Service]
Type=oneshot
Environment=ROOT=/opt/usersim_fm
Environment=DPO_SERVICE=usersim-dpo-socrates.service
ExecStart=/usr/bin/python3 -u /opt/usersim_fm/scripts/fm_train/dpo_watchdog.py
Nice=10
EOF

cat > /etc/systemd/system/usersim-dpo-watchdog.timer <<'EOF'
[Unit]
Description=UserSim Socrates DPO watchdog every 5 min

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s
Unit=usersim-dpo-watchdog.service

[Install]
WantedBy=timers.target
EOF

# Stop SFT service so it cannot fight DPO for the GPU.
systemctl disable --now usersim-sft-socrates.service 2>/dev/null || true
systemctl disable --now usersim-sft-watchdog.timer 2>/dev/null || true

systemctl daemon-reload
systemctl enable usersim-dpo-socrates.service
systemctl enable --now usersim-dpo-watchdog.timer
systemctl restart usersim-dpo-socrates.service
systemctl --no-pager --full status usersim-dpo-socrates.service | head -25
echo INSTALL_DPO_UNITS_OK
