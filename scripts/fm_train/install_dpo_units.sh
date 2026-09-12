#!/bin/bash
# Install / refresh Socrates DPO systemd units on the SFT L4 VM.
# Idempotent. Called after scp of scripts/fm_train/*dpo*.
set -euo pipefail
ROOT=/opt/usersim_fm
mkdir -p "$ROOT/results" "$ROOT/adapters" "$ROOT/data" "$ROOT/results/socrates_dpo"

# Prevent SFT from fighting DPO for the GPU (including after Spot reboot).
systemctl disable --now usersim-sft-socrates.service 2>/dev/null || true
systemctl disable --now usersim-sft-watchdog.timer 2>/dev/null || true
systemctl mask usersim-sft-socrates.service 2>/dev/null || true

cat > /etc/systemd/system/usersim-dpo-socrates.service <<'EOF'
[Unit]
Description=UserSim Socrates QLoRA DPO from ckpt-425
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/usersim_fm
Environment=ROOT=/opt/usersim_fm
Environment=PYTHONPATH=/opt/usersim_fm/scripts/fm_train
Environment=SFT_MODEL=Qwen/Qwen3-8B-Base
Environment=SFT_ADAPTER=/opt/usersim_fm/adapters/socrates_qwen3_8b_qlora/checkpoint-425
Environment=TRAIN_PY=/opt/usersim_fm/venvs/train/bin/python3
Environment=RESUME=1
Environment=LR=1e-6
# micro=2 fits L4 ~14→~20GB; keeps effective batch 64 while cutting epoch wall time ~2x.
Environment=MICRO_BATCH=2
Environment=GRAD_ACCUM=32
Environment=SAVE_STEPS=25
Environment=LOG_STEPS=1
Environment=EPOCHS=1
Environment=RUN_EVAL=1
Environment=PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
Environment=HOME=/home/ubuntu
Environment=PATH=/opt/usersim_fm/venvs/train/bin:/home/ubuntu/.local/bin:/opt/conda/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/usr/bin/python3 -u /opt/usersim_fm/scripts/fm_train/boot_socrates_dpo.py
Restart=on-failure
RestartSec=60
StartLimitIntervalSec=0
Nice=5
StandardOutput=append:/opt/usersim_fm/results/socrates_dpo.log
StandardError=append:/opt/usersim_fm/results/socrates_dpo.log
KillMode=control-group

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/usersim-dpo-watchdog.service <<'EOF'
[Unit]
Description=UserSim Socrates DPO watchdog (one poll)
After=network-online.target

[Service]
Type=oneshot
User=ubuntu
Environment=ROOT=/opt/usersim_fm
Environment=DPO_SERVICE=usersim-dpo-socrates.service
Environment=PYTHONPATH=/opt/usersim_fm/scripts/fm_train
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

# Startup metadata re-enable after Spot reboot (same pattern as SFT).
# Append to existing startup-script if present; otherwise write a small one.
python3 - <<'PY'
import json, subprocess
meta = subprocess.check_output(
    ["curl", "-s", "-H", "Metadata-Flavor: Google",
     "http://metadata.google.internal/computeMetadata/v1/instance/attributes/startup-script"],
    text=True,
)
marker = "usersim-dpo-socrates.service"
snippet = """
# --- usersim dpo revive ---
systemctl unmask usersim-sft-socrates.service 2>/dev/null || true
systemctl disable --now usersim-sft-socrates.service 2>/dev/null || true
systemctl mask usersim-sft-socrates.service 2>/dev/null || true
systemctl daemon-reload
systemctl enable --now usersim-dpo-watchdog.timer
systemctl enable --now usersim-dpo-socrates.service
# --- end usersim dpo revive ---
"""
if marker not in meta:
    new = meta.rstrip() + "\n" + snippet
    open("/tmp/startup_with_dpo.sh", "w").write(new)
    print("STARTUP_NEEDS_UPDATE")
else:
    print("STARTUP_ALREADY_HAS_DPO")
PY

systemctl daemon-reload
systemctl enable usersim-dpo-socrates.service
systemctl enable --now usersim-dpo-watchdog.timer
# Clear any stale stamps from a partial prior attempt only if user asks; keep them
# for resume. Fresh start when FORMAT_SMOKE not yet stamped.
systemctl restart usersim-dpo-socrates.service
sleep 2
systemctl --no-pager --full status usersim-dpo-socrates.service | head -30
echo INSTALL_DPO_UNITS_OK
