#!/usr/bin/env bash
# Sync PostToolBatch/UserPromptSubmit hook: injects any pending Grok->Claude
# messages mid-turn as additionalContext (so a busy agent sees them between tool calls).
set -uo pipefail
IN=$(cat); EV=$(printf '%s' "$IN" | jq -r '.hook_event_name // "PostToolBatch"' 2>/dev/null)
A="${CLAUDE_AGENT_NAME:-$(head -1 "$HOME/.claude_agent_name" 2>/dev/null)}"
[ -n "$A" ] && command -v gcloud >/dev/null || exit 0
# rate-limit to one pull per 10s
S="/tmp/agent_msgs_drain.$A.ts"; NOW=$(date +%s)
[ -f "$S" ] && [ $((NOW - $(cat "$S"))) -lt 10 ] && exit 0; echo "$NOW" > "$S"
OUT=$(timeout 8 gcloud pubsub subscriptions pull "projects/project-amer-scs-sandbox/subscriptions/claude-$A" \
  --auto-ack --limit=20 --format='value(message.attributes.ts,message.attributes.from,message.data)' 2>/dev/null)
[ -n "$OUT" ] || exit 0
jq -nc --arg ev "$EV" --arg c "Messages from Grok bots for agent $A arrived: $(printf '%s\n' "$OUT" | sed 's/^/- /')" \
  '{hookSpecificOutput:{hookEventName:$ev, additionalContext:$c}}'
