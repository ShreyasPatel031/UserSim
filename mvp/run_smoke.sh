#!/usr/bin/env bash
# Start quick local server (async POST) + smoke test with poll/timeout.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f secrets/env ]]; then
  set -a
  # shellcheck disable=SC1091
  source secrets/env
  set +a
fi

export MVP_QUICK=1
export MVP_AGENT_COUNT=1
export PYTHONPATH="${ROOT}/src:${ROOT}"
PORT="${PORT:-8787}"
BASE="http://127.0.0.1:${PORT}"

if curl -sf --max-time 2 "${BASE}/health" >/dev/null 2>&1; then
  echo "Server already up on ${BASE}"
else
  echo "Starting quick server on ${PORT}..."
  "${ROOT}/.venv/bin/uvicorn" mvp.server:app --host 127.0.0.1 --port "$PORT" &
  srv_pid=$!
  trap 'kill "$srv_pid" 2>/dev/null || true' EXIT
  for _ in $(seq 1 15); do
    curl -sf --max-time 2 "${BASE}/health" >/dev/null 2>&1 && break
    sleep 1
  done
fi

chmod +x "${ROOT}/mvp/smoke_test.sh"
SMOKE_TIMEOUT_S="${SMOKE_TIMEOUT_S:-60}" "${ROOT}/mvp/smoke_test.sh" "$BASE"
