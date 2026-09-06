#!/usr/bin/env bash
# Install systemd units so Gate-0 workers auto-resume on every boot
# (including Spot preemption STOP → start).
# Usage on the VM: bash install_vm_autoresume.sh socrates|befm|minitaur
set -euo pipefail
JOB="${1:?socrates|befm|minitaur}"
ROOT=/opt/usersim_fm
USER_NAME="${SUDO_USER:-${USER:-shreyaspatel}}"
HOME_DIR=$(eval echo "~$USER_NAME")

sudo mkdir -p "$ROOT"/{scripts,results,logs,bin}
sudo chown -R "$USER_NAME:$USER_NAME" "$ROOT"

case "$JOB" in
  socrates)
    UNIT=usersim-socrates
    cat >"$ROOT/bin/run_socrates.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
export HOME="${HOME:-/home/shreyaspatel}"
# Always run foreground via hot_restart (exec's python).
if [[ -x /opt/usersim_fm/hot_restart_socrates_l4.sh ]]; then
  exec bash /opt/usersim_fm/hot_restart_socrates_l4.sh
fi
exec bash /tmp/hot_restart_socrates_l4.sh
EOF
    ;;
  befm)
    UNIT=usersim-befm
    cat >"$ROOT/bin/run_befm.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
export HOME="${HOME:-/home/shreyaspatel}"
export PATH="/opt/usersim_fm/.venv/bin:$HOME/.local/bin:/usr/local/bin:$PATH"
export HF_TOKEN="$(cat "$HOME/.cache/huggingface/token" 2>/dev/null || true)"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
if [[ -x /opt/usersim_fm/hot_cutover_befm_vllm.sh ]]; then
  bash /opt/usersim_fm/hot_cutover_befm_vllm.sh
else
  bash /tmp/hot_cutover_befm_vllm.sh
fi
# follow driver pid
while kill -0 "$(cat /opt/usersim_fm/results/befm_full.pid)" 2>/dev/null; do sleep 30; done
exit 1
EOF
    ;;
  minitaur)
    UNIT=usersim-minitaur
    cat >"$ROOT/bin/run_minitaur.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
export HOME="${HOME:-/home/shreyaspatel}"
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"
export HF_TOKEN="$(cat "$HOME/.cache/huggingface/token" 2>/dev/null || true)"
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
export UNSLOTH_SKIP_TORCHVISION_CHECK=1
export SKIP_INSTALL=1
if [[ -x /opt/usersim_fm/hot_restart_minitaur.sh ]]; then
  bash /opt/usersim_fm/hot_restart_minitaur.sh
elif [[ -x /tmp/hot_restart_minitaur.sh ]]; then
  bash /tmp/hot_restart_minitaur.sh
else
  mkdir -p /content
  ln -sfn /opt/usersim_fm /content/fm_baselines
  cd /content/fm_baselines
  pkill -f colab_minitaur_psych101_nll.py 2>/dev/null || true
  sleep 2
  nohup env SMOKE_N=0 MAX_SEQ=4096 SKIP_INSTALL=1 UNSLOTH_SKIP_TORCHVISION_CHECK=1 \
    HF_TOKEN="$HF_TOKEN" HUGGING_FACE_HUB_TOKEN="$HF_TOKEN" \
    python3 -u scripts/colab_minitaur_psych101_nll.py \
    > /opt/usersim_fm/logs/minitaur_full.log 2>&1 &
  echo $! > /opt/usersim_fm/results/minitaur_full.pid
fi
while kill -0 "$(cat /opt/usersim_fm/results/minitaur_full.pid)" 2>/dev/null; do sleep 30; done
exit 1
EOF
    ;;
  *)
    echo "unknown job $JOB"; exit 1
    ;;
esac

chmod +x "$ROOT/bin/run_${JOB}.sh"

# Copy hot scripts into persistent location if present in /tmp
for f in hot_restart_socrates_l4.sh hot_cutover_befm_vllm.sh; do
  [[ -f /tmp/$f ]] && cp /tmp/$f "$ROOT/$f" && chmod +x "$ROOT/$f"
done

sudo tee /etc/systemd/system/${UNIT}.service >/dev/null <<EOF
[Unit]
Description=UserSim Gate0 ${JOB} worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${ROOT}
Environment=HOME=${HOME_DIR}
ExecStart=${ROOT}/bin/run_${JOB}.sh
Restart=on-failure
RestartSec=60
# Spot preemption sends SIGTERM; give the worker a moment to flush
TimeoutStopSec=30
KillMode=mixed
StandardOutput=append:${ROOT}/logs/${UNIT}.systemd.log
StandardError=append:${ROOT}/logs/${UNIT}.systemd.log

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${UNIT}.service"

healthy=0
case "$JOB" in
  socrates)
    if [[ -f $ROOT/results/socrates_vllm.pid ]] && ps -p "$(cat $ROOT/results/socrates_vllm.pid)" >/dev/null 2>&1; then
      healthy=1
    fi
    ;;
  befm)
    if [[ -f $ROOT/results/befm_full.pid ]] && ps -p "$(cat $ROOT/results/befm_full.pid)" >/dev/null 2>&1; then
      healthy=1
    fi
    ;;
  minitaur)
    if pgrep -f colab_minitaur_psych101_nll.py >/dev/null 2>&1; then
      healthy=1
    fi
    ;;
esac

if [[ "$healthy" == "1" ]]; then
  echo "enabled ${UNIT}; worker already healthy — not restarting now (will auto-start on next boot/preempt)"
else
  echo "enabled ${UNIT}; worker unhealthy — starting"
  sudo systemctl start "${UNIT}.service" || true
fi
systemctl is-enabled "${UNIT}.service" || true
echo "INSTALLED ${UNIT} (WantedBy=multi-user.target → runs on every boot)"
