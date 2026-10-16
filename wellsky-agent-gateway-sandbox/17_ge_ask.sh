#!/usr/bin/env bash
# Ask the wsky Gemini Enterprise app a question through its assistant (the same path as the GE web UI).
#   ./17_ge_ask.sh "question"
set -uo pipefail; source "$(dirname "$0")/env.sh"
E=https://us-discoveryengine.googleapis.com/v1/projects/$PROJECT_ID/locations/us/collections/default_collection/engines/${PREFIX}-ge-app
curl -sS -m 120 -X POST -H "Authorization: Bearer $(tok)" -H "Content-Type: application/json" -H "X-Goog-User-Project: $PROJECT_ID" \
  "$E/assistants/default_assistant:streamAssist" -d "$(python3 -c 'import json,sys;print(json.dumps({"query":{"text":sys.argv[1]}}))' "$1")" |
python3 -c '
import json, sys
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except Exception:
    print("RAW", raw[:800]); sys.exit()
items = data if isinstance(data, list) else [data]
text = []
for it in items:
    if "error" in it: print("ERROR", json.dumps(it["error"])[:600]); continue
    for r in (it.get("answer") or {}).get("replies", []):
        t = (r.get("groundedContent") or {}).get("content", {}).get("text")
        if t and not (r.get("groundedContent") or {}).get("content", {}).get("thought"): text.append(t)
    if it.get("answer", {}).get("state"): state = it["answer"]["state"]
print("ANSWER", "".join(text)[:600] or "(empty)", "| state:", locals().get("state"))'
