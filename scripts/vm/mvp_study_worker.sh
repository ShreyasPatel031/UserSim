#!/usr/bin/env bash
# Remote MVP study worker: headed Chromium under Xvfb, live GCS uploads, self-delete.
# Designed for Spot copies of the usersim-mvp-seed image (deps pre-baked).
set -euo pipefail
cd "$HOME/usersim"

export DEBIAN_FRONTEND=noninteractive
export BROWSER_HEADLESS=0
export DISPLAY="${DISPLAY:-:99}"
export MVP_BROWSER_HEADLESS=0
export MVP_FORCE_LOCAL_BROWSER=1
export MVP_BROWSER_CHANNEL="${MVP_BROWSER_CHANNEL:-0}"
export PYTHONPATH="${HOME}/usersim/src:${HOME}/usersim"

GOOGLE_AUTH_VERSION="2.41.1"
GOOGLE_AUTH_PIN="google-auth==${GOOGLE_AUTH_VERSION}"

# Absolute TTL backup (startup script also arms shutdown -h).
TTL_MIN="${MVP_GCP_FLEET_TTL_MIN:-25}"
shutdown -h "+${TTL_MIN}" 2>/dev/null || true

echo "==> stop apt noise"
sudo systemctl stop unattended-upgrades.service 2>/dev/null || true
sudo systemctl disable unattended-upgrades.service 2>/dev/null || true
sudo killall apt-get apt dpkg 2>/dev/null || true
sleep 1

if [[ "${MVP_SKIP_APT:-0}" == "1" ]]; then
  echo "==> seeded image — skipping full apt bootstrap"
  if [[ ! -d .venv ]] && ! python3 -c "import ensurepip" 2>/dev/null; then
    echo "==> installing python3-venv (one-shot)"
    timeout 120 sudo apt-get install -y -qq python3-venv python3-pip \
      || timeout 120 sudo apt-get install -y -qq python3.11-venv python3-pip \
      || echo "WARN: could not install python3-venv"
  fi
else
  echo "==> apt (GCE mirror)"
  printf '%s\n' \
    'deb http://us-central1.gce.archive.ubuntu.com/ubuntu/ noble main restricted universe multiverse' \
    'deb http://us-central1.gce.archive.ubuntu.com/ubuntu/ noble-updates main restricted universe multiverse' \
    'deb http://us-central1.gce.archive.ubuntu.com/ubuntu/ noble-security main restricted universe multiverse' \
    | sudo tee /etc/apt/sources.list >/dev/null
  sudo rm -f /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources 2>/dev/null || true
  timeout 90 sudo apt-get -o Acquire::http::Timeout=20 -o Acquire::Retries=2 update -qq \
    || echo "WARN: apt update timed out"
  timeout 180 sudo apt-get install -y -qq xvfb python3-venv python3-pip \
    || echo "WARN: apt install partial"
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -U pip wheel
  .venv/bin/pip install -q 'browser-use==0.13.8' playwright google-genai "$GOOGLE_AUTH_PIN" \
    'google-cloud-storage>=2.14' 'google-cloud-compute>=1.19' httpx pydantic
  .venv/bin/playwright install chromium
  sudo .venv/bin/playwright install-deps chromium 2>/dev/null || true
else
  # google-auth 2.48.0 broke GCE metadata auth (_prepare_request_for_mds reads
  # request.session on a transport that has none), which kills ADC on copies.
  have=$(.venv/bin/python -c 'import importlib.metadata as m; print(m.version("google-auth"))' 2>/dev/null || echo 0)
  if [[ "$have" != "$GOOGLE_AUTH_VERSION" ]]; then
    .venv/bin/pip install -q "$GOOGLE_AUTH_PIN" || echo "WARN: google-auth pin failed (have $have)"
  fi
  .venv/bin/pip install -q 'google-cloud-storage>=2.14' 'google-cloud-compute>=1.19' 2>/dev/null || true
fi

if ! pgrep -f "Xvfb ${DISPLAY}" >/dev/null 2>&1; then
  Xvfb "$DISPLAY" -screen 0 1440x900x24 >/tmp/xvfb.log 2>&1 &
  sleep 1
  echo "Started Xvfb on $DISPLAY"
fi

mkdir -p secrets
if [[ -f secrets/env ]]; then
  set -a
  # shellcheck disable=SC1091
  source secrets/env
  set +a
fi

# secrets/env carries the operator's laptop paths. A credential pointer to a
# file that does not exist here makes google.auth.default() raise instead of
# falling through to the instance service account.
for var in GOOGLE_APPLICATION_CREDENTIALS CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE VERTEX_ADC; do
  path="${!var:-}"
  if [[ -n "$path" && ! -f "$path" ]]; then
    unset "$var"
    echo "unset $var (dangling: $path)"
  fi
done

# Optional signed-in profile seam (owned by another agent; off by default).
if [[ "${MVP_SEED_PROFILE:-0}" == "1" ]]; then
  SEED_CHROME=$(ls -d /var/lib/usersim-seed/*/chrome 2>/dev/null | head -1 || true)
  if [[ -n "${SEED_CHROME}" && -d "${SEED_CHROME}" ]]; then
    mkdir -p secrets/product_profiles
    ln -sfn "$SEED_CHROME" secrets/youtube_browser_profile
    ln -sfn "$SEED_CHROME" secrets/product_profiles/youtube.com
    echo "Linked seed Chrome profile from $SEED_CHROME"
  fi
else
  export MVP_DISABLE_PROFILE_POOL=1
  echo "Public browsing — profile pool disabled"
fi

# Prefer instance service-account ADC. Only use a key file if explicitly present.
if [[ -f "${HOME}/usersim/secrets/sa.json" ]]; then
  export GOOGLE_APPLICATION_CREDENTIALS="${HOME}/usersim/secrets/sa.json"
  export CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE="${HOME}/usersim/secrets/sa.json"
fi
export MVP_BROWSER_HEADLESS=0
export MVP_FORCE_LOCAL_BROWSER=1
export MVP_BROWSER_CHANNEL="${MVP_BROWSER_CHANNEL:-0}"
export MVP_CHROMIUM_NO_SANDBOX=1
export BROWSER_HEADLESS=0
export DISPLAY

JOB="${HOME}/usersim/job.json"
.venv/bin/python scripts/vm/mvp_study_worker.py --job "$JOB"
rc=$?
echo "WORKER_EXIT=$rc"

KEEP_VM="${KEEP_VM:-0}"
if [[ -f "$JOB" ]]; then
  KEEP_VM=$(.venv/bin/python -c "import json; print('1' if json.load(open('$JOB')).get('keep_vm') else '0')" 2>/dev/null || echo 0)
fi

if [[ "$KEEP_VM" == "1" ]]; then
  echo "KEEP_VM=1, leaving instance up"
  exit "$rc"
fi

meta="http://metadata.google.internal/computeMetadata/v1/instance"
name=$(curl -sf -H 'Metadata-Flavor: Google' "$meta/name" || true)
zone=$(curl -sf -H 'Metadata-Flavor: Google' "$meta/zone" | awk -F/ '{print $NF}' || true)
# Prefer Compute API delete via python (no gcloud required on image).
if [[ -n "$name" && -n "$zone" ]]; then
  .venv/bin/python - <<PY || true
from google.cloud import compute_v1
import os
name, zone = "$name", "$zone"
project = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "project-amer-scs-sandbox"
client = compute_v1.InstancesClient()
try:
    op = client.delete(project=project, zone=zone, instance=name)
    print(f"delete requested for {name}")
except Exception as e:
    print(f"delete via API failed: {e}")
PY
  if command -v gcloud >/dev/null 2>&1; then
    gcloud compute instances delete "$name" --zone="$zone" --quiet && exit "$rc"
  fi
fi
sudo poweroff
