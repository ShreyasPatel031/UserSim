#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src
exec .venv/bin/uvicorn mvp.server:app --reload --port 8787
