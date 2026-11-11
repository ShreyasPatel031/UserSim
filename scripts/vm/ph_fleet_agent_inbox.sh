#!/usr/bin/env bash
# Durable consume: persist then ack (default).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PROJECT="${AGENT_MSGS_PROJECT:?set AGENT_MSGS_PROJECT}"
SUB="${AGENT_MSGS_SUB:-fleet-cursor}"
LIMIT="${1:-10}"
RUN_ID="${PACE_FLEET_RUN_ID:-}"
ART="${FLEET_ART:-}"
if [[ -z "$ART" && -n "$RUN_ID" ]]; then
  ART="$(cd "$ROOT/../.." && pwd)/results/ph_fleet_full/${RUN_ID,,}"
fi
OUT="${AGENT_INBOX_JSONL:-${ART:-/tmp}/agent_inbox/${SUB}.jsonl}"
TAG="${2:-}"
exec python3 "$ROOT/ph_fleet_agent_inbox_consume.py" \
  --project="$PROJECT" \
  --subscription="$SUB" \
  --out="$OUT" \
  --limit="$LIMIT" \
  --ack \
  ${TAG:+--once-tag "$TAG"}
