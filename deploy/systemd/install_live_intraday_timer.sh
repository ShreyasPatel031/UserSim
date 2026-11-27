#!/usr/bin/env bash
# Install and enable the UserSim Core v5 Pre-Reveal Intraday systemd timer (`00:12, 01:10, 02:20, 03:35 PT`).
set -euo pipefail

REPO_DIR="${1:-$HOME/UserSim}"
DATA_DIR="${2:-/tmp/usersim_work/data}"
USER_NAME="$(id -un)"

TMP_SVC="$(mktemp)"
sed -e "s|User=shreyaspatel|User=${USER_NAME}|g" \
    -e "s|/home/shreyaspatel/UserSim|${REPO_DIR}|g" \
    -e "s|/tmp/usersim_work/data|${DATA_DIR}|g" \
    "${REPO_DIR}/deploy/systemd/usersim-live-pre.service" > "${TMP_SVC}"

sudo cp "${TMP_SVC}" /etc/systemd/system/usersim-live-pre.service
sudo cp "${REPO_DIR}/deploy/systemd/usersim-live-pre.timer" /etc/systemd/system/usersim-live-pre.timer
rm -f "${TMP_SVC}"

sudo systemctl daemon-reload
sudo systemctl enable --now usersim-live-pre.timer
systemctl list-timers usersim-live-pre.timer --no-pager
