#!/usr/bin/env bash
# Restore cloud secrets into ./secrets/ (run on a VM or Cursor cloud agent).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

GCS_URI="${1:-gs://usersim-bakeoff-347838016394/secrets/usersim-cloud-secrets-latest.tgz}"
TMP="$(mktemp -t usersim-secrets.XXXXXX.tgz)"
trap 'rm -f "$TMP"' EXIT

echo "Pulling $GCS_URI ..."
gsutil cp "$GCS_URI" "$TMP"
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
