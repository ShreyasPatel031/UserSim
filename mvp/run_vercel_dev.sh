#!/usr/bin/env bash
# Local Vercel-mode dev server (same env + sync POST behavior as production).
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

export VERCEL=1
export MVP_QUICK="${MVP_QUICK:-1}"
export MVP_MAX_STEPS="${MVP_MAX_STEPS:-8}"
export MVP_BROWSER_CONCURRENCY="${MVP_BROWSER_CONCURRENCY:-2}"
export MVP_AGENT_COUNT="${MVP_AGENT_COUNT:-1}"
export MVP_STUDY_TIMEOUT_S="${MVP_STUDY_TIMEOUT_S:-90}"
export BROWSERBASE_CREATE_INTERVAL_S="${BROWSERBASE_CREATE_INTERVAL_S:-8}"
export PYTHONPATH="${ROOT}/src:${ROOT}"

PORT="${PORT:-3000}"
echo "UserSim Vercel-mode dev → http://127.0.0.1:${PORT}"
echo "  VERCEL=1  MVP_QUICK=${MVP_QUICK}  MVP_AGENT_COUNT=${MVP_AGENT_COUNT}  (snapshot, no live browser)"
exec "${ROOT}/.venv/bin/uvicorn" mvp.server:app --host 127.0.0.1 --port "$PORT" --reload
