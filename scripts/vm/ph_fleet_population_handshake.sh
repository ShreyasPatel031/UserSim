#!/usr/bin/env bash
# Population ↔ fleet-cursor comms (authorized: messaging/audit only).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$ROOT/../.." && pwd)"
source "${PACE_ENV_FILE:-$REPO/results/ph_tab_experiment/20261107t170953z/pace.env}"
export GCP_PROJECT PACE_ZONE MVP_GCS_BUCKET PACE_GCS_VM_ROOT
RUN_ID="${PACE_FLEET_RUN_ID:-$(cat "$REPO/results/ph_fleet_full/latest_run.txt")}"
RUN_ID="${RUN_ID,,}"
ART="$REPO/results/ph_fleet_full/${RUN_ID}"
export FLEET_ART="$ART" PACE_FLEET_RUN_ID="$RUN_ID"
export AGENT_MSGS_PROJECT="${AGENT_MSGS_PROJECT:-${GCP_PROJECT:-}}"
[[ -n "$AGENT_MSGS_PROJECT" ]] || { echo "AGENT_MSGS_PROJECT required" >&2; exit 1; }
export FLEET_PKG="${FLEET_PKG:-bsit_full17.tgz}"
export FLEET_PKG_MD5="${FLEET_PKG_MD5:-Ku9PrVAfo8f+uDrIVfW8Bg==}"
mkdir -p "$ART/agent_inbox"

# 1) One-time read of cursor-fleet setup queue (durable, then ack)
AGENT_INBOX_JSONL="$ART/agent_inbox/cursor-fleet.jsonl" \
  AGENT_MSGS_SUB=cursor-fleet \
  bash "$ROOT/ph_fleet_agent_inbox.sh" 20 setup-contract || true

# 2) Canonical receiver fleet-cursor
AGENT_INBOX_JSONL="$ART/agent_inbox/fleet-cursor.jsonl" \
  AGENT_MSGS_SUB=fleet-cursor \
  bash "$ROOT/ph_fleet_agent_inbox.sh" 20 pre-handshake || true

HANDOFF="$(python3 "$ROOT/ph_fleet_population_audit_packet.py")"
TEST_MSG="DIRECT_TEST run=${RUN_ID} nonce_ref=NONCE-CUR-1794164348 from=fleet-cursor. Reply to=fleet-cursor with POPULATION_PONG and audit_accepted=true/false. ${HANDOFF}"
"$ROOT/ph_fleet_agent_relay.sh" population fleet-cursor "$TEST_MSG"
"$ROOT/ph_fleet_agent_relay.sh" population fleet-cursor \
  "REQUEST_FULL_AUDIT: audit every gs object under ${PACE_GCS_VM_ROOT}/ — lists-only never complete; return repair_list with handle, missing_fields, pagination_end_evidence."

ACK_MSG="ACK CURSOR-CONTRACT run=${RUN_ID} receiver=fleet-cursor durable_inbox=${ART}/agent_inbox/ output=${PACE_GCS_VM_ROOT}/ pkg=${FLEET_PKG} md5=${FLEET_PKG_MD5} status=relay_to_population_active zero_incomplete=UNVERIFIED"
"$ROOT/ph_fleet_agent_relay.sh" grokbot fleet-cursor "$ACK_MSG"

sleep 3
AGENT_INBOX_JSONL="$ART/agent_inbox/fleet-cursor.jsonl" \
  AGENT_MSGS_SUB=fleet-cursor \
  bash "$ROOT/ph_fleet_agent_inbox.sh" 10 post-test || true

echo "HANDSHAKE_DONE art=$ART"
