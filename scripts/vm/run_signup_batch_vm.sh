#!/usr/bin/env bash
# Small GCP smoke: headed Chrome signup under Xvfb, then DELETE the VM.
#
# Usage:
#   SIGNUP_LIMIT=3 ./scripts/vm/run_signup_batch_vm.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PROJECT="${GCP_PROJECT:-project-amer-scs-sandbox}"
ZONE="${GCP_ZONE:-us-central1-b}"
MACHINE="${GCP_MACHINE:-e2-small}"
NAME="${VM_NAME:-usersim-signup-$(date +%y%m%d-%H%M%S)}"
PARALLEL="${SIGNUP_PARALLEL:-1}"
TIMEOUT_S="${SIGNUP_TIMEOUT_S:-120}"
MAX_STEPS="${SIGNUP_MAX_STEPS:-18}"
LIMIT="${SIGNUP_LIMIT:-3}"
KEEP_VM="${KEEP_VM:-0}"
DISK_GB="${GCP_DISK_GB:-30}"
GCS_PREFIX="${GCS_PREFIX:-gs://usersim-bakeoff-347838016394}"

SSH=(gcloud compute ssh "$NAME" --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap)
SCP=(gcloud compute scp --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap)

[[ -f secrets/env ]] || { echo "ERROR: secrets/env missing"; exit 1; }
[[ -f secrets/credentials.json ]] || { echo "ERROR: secrets/credentials.json missing"; exit 1; }

echo "==> Creating $NAME ($MACHINE, disk=${DISK_GB}G, limit=${LIMIT})"
gcloud compute instances create "$NAME" \
  --project="$PROJECT" \
  --zone="$ZONE" \
  --machine-type="$MACHINE" \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size="${DISK_GB}GB" \
  --boot-disk-type=pd-balanced \
  --network=main-vpc \
  --subnet=primary-subnet \
  --scopes=cloud-platform \
  --tags=allow-iap-ssh \
  --quiet

cleanup() {
  local rc=$?
  if [[ "$KEEP_VM" == "0" ]]; then
    echo "==> Deleting $NAME (KEEP_VM=0)"
    gcloud compute instances delete "$NAME" --project="$PROJECT" --zone="$ZONE" --quiet || true
  else
    echo "==> KEEP_VM=1 — left $NAME running"
  fi
  exit "$rc"
}
trap cleanup EXIT

echo "==> Waiting for SSH"
for _ in $(seq 1 60); do
  if "${SSH[@]}" --command="echo up" --quiet 2>/dev/null; then
    break
  fi
  sleep 3
done
"${SSH[@]}" --command="echo up" --quiet

# One tarball — recursive scp over IAP hangs on this network.
echo "==> Packing payload"
TAR="$(mktemp -t usersim-signup.XXXXXX.tgz)"
tar -C "$ROOT" -czf "$TAR" \
  --exclude='mvp/runs' \
  --exclude='**/__pycache__' \
  --exclude='.venv' \
  --no-xattrs \
  --disable-copyfile \
  src mvp requirements.txt pyproject.toml \
  secrets/env secrets/credentials.json 2>/dev/null \
|| tar -C "$ROOT" -czf "$TAR" \
  --exclude='mvp/runs' \
  --exclude='**/__pycache__' \
  --exclude='.venv' \
  src mvp requirements.txt pyproject.toml \
  secrets/env secrets/credentials.json
ls -lh "$TAR"

echo "==> Uploading tarball"
"${SSH[@]}" --command="mkdir -p ~/usersim"
"${SCP[@]}" "$TAR" "$NAME:~/usersim/payload.tgz" --quiet
rm -f "$TAR"

echo "==> Remote setup + signup batch"
# Line-buffered so hung apt/pip is visible over IAP SSH.
"${SSH[@]}" --command="stdbuf -oL -eL bash -s" <<REMOTE
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
cd ~/usersim
echo "==> extract"
tar -xzf payload.tgz
rm -f payload.tgz

# Unattended upgrades hold apt locks and stall chrome deps on small VMs.
echo "==> stop apt noise"
sudo systemctl stop unattended-upgrades.service 2>/dev/null || true
sudo systemctl disable unattended-upgrades.service 2>/dev/null || true
sudo killall apt-get apt dpkg 2>/dev/null || true
sleep 1

echo "==> apt via GCE mirror + uv python (avoid hung archive.ubuntu.com)"
# Point apt at the regional GCE mirror; plain archive.ubuntu.com hangs on this VPC.
# No heredocs here — remote script is fed on stdin via bash -s.
printf '%s\n' \
  'deb http://us-central1.gce.archive.ubuntu.com/ubuntu/ noble main restricted universe multiverse' \
  'deb http://us-central1.gce.archive.ubuntu.com/ubuntu/ noble-updates main restricted universe multiverse' \
  'deb http://us-central1.gce.archive.ubuntu.com/ubuntu/ noble-security main restricted universe multiverse' \
  | sudo tee /etc/apt/sources.list >/dev/null
sudo rm -f /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources 2>/dev/null || true
timeout 90 sudo apt-get -o Acquire::http::Timeout=20 -o Acquire::Retries=2 update -qq \
  || echo "WARN: apt update timed out/failed"
timeout 120 sudo apt-get -o Acquire::http::Timeout=20 -o Acquire::Retries=2 install -y -qq \
  xvfb python3.12-venv python3-dev wget gnupg \
  libgtk-3-0 libx11-xcb1 libasound2t64 fonts-liberation libnss3 \
  libatk-bridge2.0-0 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
  libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libxshmfence1 libcups2 \
  >/tmp/apt_install.log 2>&1 || {
    echo "WARN: apt install partial; log:"; tail -30 /tmp/apt_install.log || true
  }
python3 --version
command -v Xvfb && echo "Xvfb ok" || echo "WARN: Xvfb missing — will use headless"

echo "==> uv + venv"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="\$HOME/.local/bin:\$PATH"
uv venv .venv --python 3.12
uv pip install -q 'fastapi>=0.115' 'uvicorn[standard]>=0.32' 'httpx>=0.28' 'pyotp>=2.9' \
  playwright 'browser-use==0.13.8' 'browserbase>=1.0' pydantic

echo "==> playwright chromium"
.venv/bin/playwright install chromium

echo "==> display"
export DISPLAY=:99
HEADLESS_FLAG=0
if command -v Xvfb >/dev/null 2>&1; then
  pkill -f 'Xvfb :99' 2>/dev/null || true
  Xvfb :99 -screen 0 1440x900x24 >/tmp/xvfb.log 2>&1 &
  sleep 1
else
  echo "WARN: no Xvfb — headless Chrome"
  HEADLESS_FLAG=1
fi

set -a
# shellcheck disable=SC1091
source secrets/env
set +a
export SIGNUP_PARALLEL=${PARALLEL}
export SIGNUP_TIMEOUT_S=${TIMEOUT_S}
export SIGNUP_MAX_STEPS=${MAX_STEPS}
export SIGNUP_LIMIT=${LIMIT}
export SIGNUP_HEADLESS=\$HEADLESS_FLAG
export MVP_CAPTCHA_ALLOW_HUMAN=0
export MVP_BROWSER_HEADLESS=\$HEADLESS_FLAG
# Prefer Playwright Chromium when Google Chrome is absent.
# NOTE: escape \$ and \$( so they expand on the VM, not locally.
CHROME_CAND=\$(find "\$HOME/.cache/ms-playwright" \\( -type f -o -type l \\) -name chrome -path '*/chrome-linux*/chrome' 2>/dev/null | head -1 || true)
if [[ -z "\$CHROME_CAND" ]]; then
  CHROME_CAND=\$(.venv/bin/python -c 'from playwright.sync_api import sync_playwright
with sync_playwright() as p: print(p.chromium.executable_path)' 2>/dev/null || true)
fi
if [[ -z "\$CHROME_CAND" || ! -e "\$CHROME_CAND" ]]; then
  echo "ERROR: Chromium not found after playwright install" >&2
  find "\$HOME/.cache/ms-playwright" -name chrome 2>/dev/null | head -20 >&2 || true
  exit 1
fi
export MVP_CHROME_PATH="\$CHROME_CAND"
echo "==> MVP_CHROME_PATH=\$MVP_CHROME_PATH"
"\$MVP_CHROME_PATH" --version || true

mkdir -p results/signup_batch secrets/product_profiles secrets/site_states secrets/signup_steps
[[ -f secrets/identities.json ]] || echo '{"products":{}}' > secrets/identities.json

echo "==> START signup batch limit=${LIMIT} parallel=${PARALLEL}"
# Batch returns 1 when all fail — do not abort before DONE (set -e).
set +e
PYTHONPATH=src:. .venv/bin/python mvp/signup_batch_parallel.py
BATCH_RC=\$?
set -e
echo "==> DONE signup batch rc=\$BATCH_RC"
ls -la results/signup_batch/ || true
tail -80 /tmp/auto_signup_chrome.log 2>/dev/null || true
exit 0
REMOTE
SSH_RC=$?

echo "==> Pulling results (ssh_rc=${SSH_RC})"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$ROOT/results/signup_batch/vm_${STAMP}"
mkdir -p "$OUT"
"${SCP[@]}" --recurse "$NAME:~/usersim/results/signup_batch/*" "$OUT/" --quiet || true
"${SCP[@]}" "$NAME:~/usersim/secrets/identities.json" "$OUT/identities.json" --quiet || true
"${SSH[@]}" --command="tail -120 /tmp/auto_signup_chrome.log 2>/dev/null; ls -la ~/usersim/results/signup_batch 2>/dev/null" \
  >"$OUT/remote_chrome_tail.txt" 2>/dev/null || true

LATEST="$(ls -t "$OUT"/batch_parallel_*_summary.json 2>/dev/null | head -1 || true)"
if [[ -n "$LATEST" ]]; then
  gcloud storage cp "$LATEST" "${GCS_PREFIX}/signup_batch/$(basename "$LATEST")" --quiet || true
  echo "DONE → $LATEST"
  python3 - <<PY
import json
from pathlib import Path
d=json.loads(Path("$LATEST").read_text())
print(json.dumps({k:d[k] for k in ("total","ok","fail","by_reason")}, indent=2))
for r in sorted(d.get("results") or [], key=lambda x: (not x.get("ok"), x.get("url") or "")):
    print(f"  {'OK' if r.get('ok') else 'FAIL':4} {r.get('url','?'):<35} {r.get('reason','?')}")
    if r.get("stderr_tail"):
        print(f"       stderr: {r['stderr_tail'][:240]!r}")
    if r.get("raw"):
        print(f"       raw: {r['raw'][:240]!r}")
PY
else
  echo "ERROR: no summary pulled — see $OUT/remote_chrome_tail.txt"
  cat "$OUT/remote_chrome_tail.txt" 2>/dev/null || true
  exit 1
fi
