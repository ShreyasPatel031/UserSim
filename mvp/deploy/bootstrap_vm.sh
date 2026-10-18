#!/usr/bin/env bash
# One-time VM setup: pull-deploy timer + migrate /etc/usersim/env secrets to Secret Manager.
# Run on usersim-grokbot-web (or any prod host) as a user with sudo and gcloud auth to project-amer-scs-sandbox.
#
#   curl -fsSL https://raw.githubusercontent.com/ShreyasPatel031/UserSim/main/mvp/deploy/bootstrap_vm.sh | sudo bash
# or from a checkout:
#   sudo bash mvp/deploy/bootstrap_vm.sh
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [ ! -f "$ROOT/mvp/deploy/vm_pull_deploy.sh" ]; then
  ROOT=$(mktemp -d)
  git clone --depth 1 https://github.com/ShreyasPatel031/UserSim.git "$ROOT"
fi
PROJECT="${USERSIM_GCP_PROJECT:-project-amer-scs-sandbox}"
ENV_FILE="${USERSIM_ENV_FILE:-/etc/usersim/env}"
APP_ROOT="${USERSIM_APP_ROOT:-/opt/usersim/app}"
BIN_DIR="${USERSIM_BIN_DIR:-/opt/usersim/bin}"
STATE_DIR="${USERSIM_STATE_DIR:-/var/lib/usersim}"

SECRET_VARS=(
  GMAIL_APP_PASSWORD BROWSERBASE_API_KEY MVP_CAPTCHA_API_KEY CAPSOLVER_API_KEY APIFY_TOKEN
  MVP_SMS_PHONE MVP_OWNER_PHONE MVP_NTFY_SMS_TOPIC MVP_NTFY_TOKEN MVP_SMS_API_KEY MVP_MCP_TOKEN
  MVP_TEXTVERIFIED_API_KEY
)

log() { echo "[bootstrap_vm] $*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "run as root: sudo bash $0" >&2
  exit 1
fi

mkdir -p "$APP_ROOT" "$BIN_DIR" "$STATE_DIR" /etc/usersim
install -m 755 "$ROOT/mvp/deploy/vm_pull_deploy.sh" "$BIN_DIR/vm_pull_deploy.sh"
install -m 644 "$ROOT/mvp/deploy/usersim-pull-deploy.service" /etc/systemd/system/usersim-pull-deploy.service
install -m 644 "$ROOT/mvp/deploy/usersim-pull-deploy.timer" /etc/systemd/system/usersim-pull-deploy.timer
systemctl daemon-reload
systemctl enable --now usersim-pull-deploy.timer
log "enabled usersim-pull-deploy.timer (every ~3 min)"

if ! command -v gcloud >/dev/null; then
  log "gcloud not found — skip Secret Manager migration (install Google Cloud SDK first)"
  exit 0
fi
gcloud config set project "$PROJECT" >/dev/null

if [ ! -f "$ENV_FILE" ]; then
  log "no $ENV_FILE — skip secret migration"
  exit 0
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE" 2>/dev/null || true
set +a

for var in "${SECRET_VARS[@]}"; do
  val="${!var:-}"
  [ -n "$val" ] || continue
  sid="usersim-${var}"
  if ! gcloud secrets describe "$sid" --project="$PROJECT" >/dev/null 2>&1; then
    log "create secret $sid"
    gcloud secrets create "$sid" --project="$PROJECT" --replication-policy=automatic
  fi
  log "add version $sid"
  printf '%s' "$val" | gcloud secrets versions add "$sid" --project="$PROJECT" --data-file=-
done

log "done. Secrets refresh on the server every ~5 min (mvp/secrets_store.py)."
log "Optional: remove secret lines from $ENV_FILE after verifying /api/mcp/limits secrets.present"
