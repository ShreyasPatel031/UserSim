#!/usr/bin/env bash
# e2e2 matrix — product URL is configurable (default Agency; pass YouTube via E2E2_URL).
#
#   E2E2_URL=https://www.youtube.com/ ./mvp/run_e2e2.sh http://127.0.0.1:3000
#   ./mvp/run_e2e2.sh http://127.0.0.1:3000 --url https://www.youtube.com/
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -f secrets/sa.json ]]; then
  export GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-$ROOT/secrets/sa.json}"
fi
export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src:$ROOT"
export E2E_BASE="${1:-${E2E_BASE:-https://usersim.vercel.app}}"
export E2E2_URL="${E2E2_URL:-https://useagency.dev/}"

python3 -m playwright install chromium >/dev/null 2>&1 || true

echo "→ e2e2 base=${E2E_BASE} url=${E2E2_URL} expected=${E2E2_EXPECTED:-75} judge=${E2E_JUDGE_MODEL:-flash-lite}"
# Remaining args after base go to the python runner (may include another --url).
exec python3 mvp/e2e2_matrix.py --base "$E2E_BASE" --url "$E2E2_URL" "${@:2}"
