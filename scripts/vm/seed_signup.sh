#!/usr/bin/env bash
# Run product signup on a seed VM. Runs ON the seed.
#
#   bash scripts/vm/seed_signup.sh todoist.com calendly.com
#
# Headed Chrome under Xvfb, low concurrency. Concurrency is deliberately small:
# the seed has one egress IP, and a burst of simultaneous signups from a single
# address is a strong bot signal regardless of how good the fingerprint is.
#
# Won sessions land on the identity disk via the symlinks provisioning created,
# so they outlive this VM.
set -euo pipefail

PARALLEL="${PARALLEL:-2}"
TIMEOUT_S="${TIMEOUT_S:-420}"
MAX_STEPS="${MAX_STEPS:-30}"

cd "$HOME/usersim"
export PATH="$HOME/.local/bin:$PATH"
export PYTHONPATH="$PWD/src:$PWD"

SEED_ID="$(curl -sf -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/instance/attributes/seed-id)"
SEED_ROOT="/var/lib/usersim-seed/${SEED_ID}"

# Detached so the SSH channel can close without taking the display down.
export DISPLAY=:99
if ! xdpyinfo -display :99 >/dev/null 2>&1; then
  echo "==> starting Xvfb :99"
  setsid nohup Xvfb :99 -screen 0 1440x900x24 >/tmp/xvfb.log 2>&1 < /dev/null &
  for _ in $(seq 1 15); do
    xdpyinfo -display :99 >/dev/null 2>&1 && break
    sleep 1
  done
fi
xdpyinfo -display :99 >/dev/null 2>&1 || { echo "FATAL: no display :99" >&2; exit 1; }
echo "==> display :99 live"

set -a
# shellcheck disable=SC1091
source secrets/env
set +a

# Headed, and never block waiting for a human to solve a captcha on a headless VM.
export MVP_BROWSER_HEADLESS=0
export MVP_CAPTCHA_ALLOW_HUMAN=0
export MVP_FORCE_LOCAL_BROWSER=1
export MVP_CHROMIUM_NO_SANDBOX=1

# browser_agent looks for a Chrome binary; Playwright's is the one we installed.
CHROME_CAND="$(find "$HOME/.cache/ms-playwright" \( -type f -o -type l \) \
  -name chrome -path '*/chrome-linux*/chrome' 2>/dev/null | head -1 || true)"
if [[ -n "$CHROME_CAND" ]]; then
  export MVP_CHROME_PATH="$CHROME_CAND"
  echo "==> chrome: $CHROME_CAND"
fi

echo "==> egress $(timeout 15 curl -sf https://api.ipify.org || echo unknown)"
echo "==> signup: $* (parallel=${PARALLEL}, headed)"

.venv/bin/python scripts/local/signup_targets.py \
  --parallel "$PARALLEL" --timeout "$TIMEOUT_S" --max-steps "$MAX_STEPS" "$@"

# Record what this seed can actually serve, verified against its own cookie jars
# rather than the global credential registry.
python3 scripts/vm/seed_status.py "$SEED_ROOT"
