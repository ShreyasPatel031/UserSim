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

# Match vercel.json production defaults so local Vercel-mode tests the real path
# (multi-persona Browserbase), not a 1-agent Quick snapshot.
export VERCEL=1
export VERCEL_ENV="${VERCEL_ENV:-development}"
export USE_BROWSERBASE="${USE_BROWSERBASE:-1}"
export MVP_VERCEL_BROWSER="${MVP_VERCEL_BROWSER:-1}"
export MVP_QUICK="${MVP_QUICK:-0}"
export MVP_MAX_STEPS="${MVP_MAX_STEPS:-8}"
# Single browser backend for now: Browserbase everywhere (local + Vercel).
# Warm GCP seeds stay for signup/fleet experiments — not the main study path.
export MVP_PREFER_GCP_FLEET="${MVP_PREFER_GCP_FLEET:-0}"
export MVP_GCP_FLEET="${MVP_GCP_FLEET:-0}"
export MVP_GCP_ALLOW_SPOT="${MVP_GCP_ALLOW_SPOT:-0}"
# 9 live agents need ~10–15 min locally; Vercel prod stays capped by maxDuration.
export MVP_STUDY_TIMEOUT_S="${MVP_STUDY_TIMEOUT_S:-900}"
# Force Developer-plan parallelism — secrets/env free-tier values must not win.
export MVP_BROWSER_CONCURRENCY=25
export BROWSERBASE_MAX_CONCURRENT=25
export BROWSERBASE_CREATE_INTERVAL_S=0
export BROWSERBASE_SESSION_TIMEOUT_S="${BROWSERBASE_SESSION_TIMEOUT_S:-1800}"
export MVP_AGENT_COUNT="${MVP_AGENT_COUNT:-5}"
export MVP_PERSONA_COUNT="${MVP_PERSONA_COUNT:-5}"
export MVP_TASK_COUNT="${MVP_TASK_COUNT:-5}"
# Force multi-persona local runs — secrets/env free-tier MVP_MAX_SESSIONS=3
# was collapsing every study to 1 user × 3 competitor sites.
export MVP_MAX_SESSIONS=15
export MVP_AGENT_CONCURRENCY="${MVP_AGENT_CONCURRENCY:-24}"
export PYTHONPATH="${ROOT}/src:${ROOT}"

PORT="${PORT:-3000}"
UVICORN_BIN="${ROOT}/.venv/bin/uvicorn"
if [[ ! -x "${UVICORN_BIN}" ]]; then
  UVICORN_BIN="$(command -v uvicorn)"
fi
echo "UserSim Vercel-mode dev → http://127.0.0.1:${PORT}"
echo "  VERCEL=1  backend=Browserbase  timeout=${MVP_STUDY_TIMEOUT_S}s  concurrency=${MVP_BROWSER_CONCURRENCY}"
exec "${UVICORN_BIN}" mvp.server:app --host 127.0.0.1 --port "$PORT" --reload \
  --reload-exclude '.vercel/*' --reload-exclude 'results/*' --reload-exclude 'mvp/runs/*'
