#!/usr/bin/env bash
# Start the UserSim backend on the VM (https://35-202-98-224.sslip.io, caddy in front).
# Loads secrets/env (template: scripts/local/env.example) and refuses to start
# without USERSIM_ADMIN_TOKEN, since kill and admin dogfood studies need it.
#   HOST/PORT (default 127.0.0.1:8080) must match caddy's reverse_proxy upstream.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f secrets/env ]]; then
  set -a
  # shellcheck disable=SC1091
  source secrets/env
  set +a
fi
if [[ -z "${USERSIM_ADMIN_TOKEN:-}" ]]; then
  echo "ERROR: USERSIM_ADMIN_TOKEN is not set. Add it to secrets/env (see deploy/README.md)." >&2
  exit 1
fi
export PYTHONPATH="src:.${PYTHONPATH:+:$PYTHONPATH}"
PY=python3
[[ -x .venv/bin/python ]] && PY=.venv/bin/python
exec "$PY" -m uvicorn mvp.server:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8080}" --timeout-keep-alive 75
