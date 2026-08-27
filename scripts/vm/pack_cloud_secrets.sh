#!/usr/bin/env bash
# Pack local secrets needed on cloud VMs / Cursor cloud agents.
# Does NOT commit secrets — writes under secrets/cloud_pack/ (gitignored via secrets/).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

need=(
  secrets/env
  secrets/vertex_adc.json
  secrets/voice_ai_sessions/bland.json
  secrets/voice_ai_sessions/vapi.json
  secrets/voice_ai_sessions/retell.json
)
for f in "${need[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: missing $f" >&2
    exit 1
  fi
done

if [[ -x .venv/bin/python ]]; then
  PYTHONPATH=src .venv/bin/python - <<'PY'
from capability.voice_ai_dashboards import write_sanitized_session
for k in ("bland", "vapi", "retell"):
    write_sanitized_session(k)
PY
fi

mkdir -p secrets/cloud_pack
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PACK="secrets/cloud_pack/usersim-cloud-secrets-${STAMP}.tgz"
tar czf "$PACK" -C "$ROOT" \
  secrets/env \
  secrets/vertex_adc.json \
  secrets/voice_ai_sessions/bland.json \
  secrets/voice_ai_sessions/vapi.json \
  secrets/voice_ai_sessions/retell.json \
  secrets/voice_ai_sessions/manifest.json
ln -sfn "$(basename "$PACK")" secrets/cloud_pack/latest.tgz
echo "Packed: $PACK ($(du -h "$PACK" | awk '{print $1}'))"

GCS_PREFIX="${GCS_PREFIX:-gs://usersim-bakeoff-347838016394/secrets}"
if [[ "${1:-}" == "--upload" ]] || [[ "${UPLOAD:-0}" == "1" ]]; then
  gsutil cp "$PACK" "${GCS_PREFIX}/usersim-cloud-secrets-${STAMP}.tgz"
  gsutil cp "$PACK" "${GCS_PREFIX}/usersim-cloud-secrets-latest.tgz"
  echo "Uploaded: ${GCS_PREFIX}/usersim-cloud-secrets-latest.tgz"
fi
