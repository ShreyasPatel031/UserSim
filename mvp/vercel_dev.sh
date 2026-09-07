#!/usr/bin/env bash
# Local Vercel-mode test before push.
#
# Default: uvicorn with VERCEL=1 + vercel.json env (same code paths as
# production: sync/stream POST, skip empty competitors, Browserbase).
#
# Real `vercel dev` Fun often OOMs here under 5 parallel Browserbase sessions
# (FUNCTION_INVOCATION_FAILED). Opt in with USE_REAL_VERCEL_DEV=1 if you have
# a linked project and want the Fun runtime.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f secrets/env ]]; then
  set -a
  # shellcheck disable=SC1091
  source secrets/env
  set +a
fi
if [[ -f .env.local ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env.local
  set +a
fi

PORT="${PORT:-3000}"
export PATH="${HOME}/.local/bin:${PATH}"

if command -v vercel >/dev/null 2>&1 && [[ "${USE_VERCEL_SHIM:-0}" != "1" ]]; then
  echo "UserSim → vercel dev --listen 127.0.0.1:${PORT}"
  export MVP_GCP_FLEET="${MVP_GCP_FLEET:-0}"
  export MVP_PREFER_GCP_FLEET="${MVP_PREFER_GCP_FLEET:-0}"
  export USE_BROWSERBASE="${USE_BROWSERBASE:-1}"
  export MVP_QUICK="${MVP_QUICK:-0}"
  exec vercel dev --listen "127.0.0.1:${PORT}" --yes
fi

echo "UserSim → Vercel-mode shim (VERCEL=1, same env as vercel.json)"
echo "  Tip: USE_REAL_VERCEL_DEV=1 to force the Vercel Fun runtime"
exec "${ROOT}/mvp/run_vercel_dev.sh"
