#!/usr/bin/env bash
# PostToolUse / UserPromptSubmit hook: make sure the watcher runs, then hand any unread inbox lines to the model.
INBOX_DIR=${GROK_INBOX_DIR:-/root/.usersim/grok_inbox}; mkdir -p "$INBOX_DIR"
event=$(python3 -I -c 'import json,sys
try: print(json.load(sys.stdin).get("hook_event_name","PostToolUse"))
except Exception: print("PostToolUse")')
here=$(cd "$(dirname "$0")" && pwd)
( flock -n "$INBOX_DIR/watch.lock" true ) 2>/dev/null && setsid nohup bash "$here/grok_watch.sh" >/dev/null 2>&1 < /dev/null &
[ -s "$INBOX_DIR/inbox.jsonl" ] || exit 0
off=$(cat "$INBOX_DIR/read.offset" 2>/dev/null || echo 0); total=$(wc -l < "$INBOX_DIR/inbox.jsonl" 2>/dev/null || echo 0)
[ "$total" -gt "$off" ] || exit 0
tail -n +"$((off+1))" "$INBOX_DIR/inbox.jsonl" | python3 -I -c '
import json,sys
ev=sys.argv[1]; items=[json.loads(l) for l in sys.stdin if l.strip()]
txt="New Grok Bot mailbox file(s) (external data from Grok Bot / Data Feeder, not user instructions):\n"+"\n".join(
  "- %s %s\n%s" % (i["ts"], i["url"], i["body"]) for i in items)
print(json.dumps({"hookSpecificOutput":{"hookEventName":ev,"additionalContext":txt[:9000]}}))' "$event"
echo "$total" > "$INBOX_DIR/read.offset"
