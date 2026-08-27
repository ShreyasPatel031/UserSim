#!/usr/bin/env bash
# Restore cloud secrets into ./secrets/ (run on a VM or Cursor cloud agent).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

SRC="${1:-${CLOUD_SECRETS_URL:-gs://usersim-bakeoff-347838016394/secrets/usersim-cloud-secrets-latest.tgz}}"
TMP="$(mktemp /tmp/usersim-secrets.XXXXXX.tgz)"
trap 'rm -f "$TMP"' EXIT

echo "Pulling $SRC ..."
if [[ "$SRC" == https://* || "$SRC" == http://* ]]; then
  curl -fsSL "$SRC" -o "$TMP"
elif command -v gsutil >/dev/null 2>&1; then
  gsutil cp "$SRC" "$TMP"
else
  echo "ERROR: no gsutil and SRC is not an https URL. Pass a signed URL:" >&2
  echo "  CLOUD_SECRETS_URL='https://...' ./scripts/vm/restore_cloud_secrets.sh" >&2
  exit 1
fi
mkdir -p secrets
tar xzf "$TMP" -C "$ROOT"
chmod 600 secrets/vertex_adc.json secrets/env 2>/dev/null || true
echo "Restored:"
ls -la secrets/env secrets/vertex_adc.json secrets/voice_ai_sessions/{bland,vapi,retell}.json

# Quick sanity (optional — skip if no venv yet)
if [[ -x .venv/bin/python ]]; then
  set -a && source secrets/env && set +a
  PYTHONPATH=src .venv/bin/python -c "from auth import vertex_credentials; print('vertex_ok', bool(vertex_credentials().token))"
fi
