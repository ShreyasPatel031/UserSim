#!/usr/bin/env bash
# Back-compat wrapper → ph_fleet_agent_relay.sh (orchestrator default).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec "$ROOT/ph_fleet_agent_relay.sh" "${1:-population}" "${2:-fleet-cursor}" "${@:3}"
