#!/usr/bin/env bash
# Pull UserSim main from public GitHub and restart the app when the SHA changes.
# No GitHub or GCP credentials required on the timer — only outbound HTTPS to github.com
# and a local systemctl restart. Install via mvp/deploy/bootstrap_vm.sh.
set -euo pipefail

REPO="${USERSIM_GITHUB_REPO:-ShreyasPatel031/UserSim}"
BRANCH="${USERSIM_GITHUB_BRANCH:-main}"
APP_ROOT="${USERSIM_APP_ROOT:-/opt/usersim/app}"
VENV="${USERSIM_VENV:-/opt/usersim/venv}"
STATE_DIR="${USERSIM_STATE_DIR:-/var/lib/usersim}"
SHA_FILE="${STATE_DIR}/deployed_sha"
BUSY_URL="${USERSIM_BUSY_URL:-http://127.0.0.1/api/runtime/status}"
SERVICE="${USERSIM_SERVICE:-usersim.service}"
WAIT_BUSY_S="${USERSIM_DEPLOY_WAIT_BUSY_S:-600}"
POLL_BUSY_S="${USERSIM_DEPLOY_POLL_BUSY_S:-10}"

log() { echo "[usersim-pull-deploy] $*"; }

mkdir -p "$STATE_DIR" "$APP_ROOT"
API="https://api.github.com/repos/${REPO}/commits/${BRANCH}"
SHA=$(curl -sf --max-time 30 -H "Accept: application/vnd.github+json" -H "User-Agent: usersim-pull-deploy" "$API" | python3 -c "import sys,json; print(json.load(sys.stdin)['sha'])")
SHORT="${SHA:0:12}"
DEPLOYED=""
[ -f "$SHA_FILE" ] && DEPLOYED=$(cat "$SHA_FILE" || true)
if [ "$SHA" = "$DEPLOYED" ]; then
  exit 0
fi
log "main moved ${DEPLOYED:-<none>} -> $SHA ($SHORT)"

elapsed=0
while [ "$elapsed" -lt "$WAIT_BUSY_S" ]; do
  busy=$(curl -sf --max-time 15 "$BUSY_URL" 2>/dev/null | python3 -c "import sys,json;d=json.load(sys.stdin);print(int(d.get('local_studies_running',0))+int(d.get('browserbase_running',0)))" 2>/dev/null || echo 0)
  if [ "${busy:-0}" = "0" ]; then
    break
  fi
  log "waiting for $busy running studies (${elapsed}s / ${WAIT_BUSY_S}s)"
  sleep "$POLL_BUSY_S"
  elapsed=$((elapsed + POLL_BUSY_S))
done

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
TARBALL="https://codeload.github.com/${REPO}/tar.gz/${BRANCH}"
curl -sfL --max-time 120 "$TARBALL" | tar -xz -C "$STAGE" --strip-components=1
for path in api mvp pyproject.toml requirements-vercel.txt results scripts src vercel.json; do
  [ -e "$STAGE/$path" ] && rsync -a "$STAGE/$path" "$APP_ROOT/"
done
echo "$SHORT $(date -u +%Y-%m-%dT%H:%M:%SZ) $BRANCH" > "$APP_ROOT/mvp/static/build.txt"
export USERSIM_ENGINE_VERSION="$SHORT"
export USERSIM_ORIGIN_SHA="$SHA"

if [ -x "$VENV/bin/pip" ]; then
  "$VENV/bin/pip" install -q -r "$APP_ROOT/requirements-vercel.txt" "uvicorn[standard]>=0.30"
  # Same pins as the old GCS deploy.sh: newer google-auth/api-core broke GCE metadata auth (Vertex) on this VM.
  "$VENV/bin/pip" install -q "google-auth==2.58.1" "google-api-core==2.39.0"
fi

# The service reads EnvironmentFile=/etc/usersim/env, so an exported USERSIM_ENGINE_VERSION here never reaches it and
# /health kept reporting the old pinned version. Rewrite only that one line (no other line is read or printed).
ENV_FILE="${USERSIM_ENV_FILE:-/etc/usersim/env}"
if [ -f "$ENV_FILE" ]; then
  if grep -q '^\(export \)\?USERSIM_ENGINE_VERSION=' "$ENV_FILE"; then
    sed -i "s/^\(export \)\?USERSIM_ENGINE_VERSION=.*/USERSIM_ENGINE_VERSION=$SHORT/" "$ENV_FILE"
  else
    echo "USERSIM_ENGINE_VERSION=$SHORT" >> "$ENV_FILE"
  fi
fi

systemctl restart "$SERVICE"
echo "$SHA" > "$SHA_FILE"
log "deployed $SHORT; build.txt and $SERVICE restarted"
