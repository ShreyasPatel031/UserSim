#!/usr/bin/env bash
# POST a request to Grok Bot's webhook. Credentials live OUTSIDE the repo in /root/.usersim/grokbot_webhook.env
# (GROKBOT_WEBHOOK_URL, GROKBOT_WEBHOOK_KEY); never commit them. Usage:
#   tools/grokbot_post.sh <agent> <need> <details> [session_url]
# Also write the same ask to mailbox/to_grokbot/ so the record stays in GCS.
set -euo pipefail
ENV=${GROKBOT_WEBHOOK_ENV:-/root/.usersim/grokbot_webhook.env}
[ -r "$ENV" ] || { echo "no credentials file at $ENV" >&2; exit 2; }
set -a; . "$ENV"; set +a
agent=$1; need=$2; details=$3; session=${4:-}
payload=$(python3 -I -c 'import json,sys,datetime; a,n,d,s=sys.argv[1:5]; print(json.dumps({"agent":a,"need":n,"details":d,"session_url":s,"ts_utc":datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}))' "$agent" "$need" "$details" "$session")
code=$(curl -sS -o /tmp/grokbot_post_resp.$$ -w '%{http_code}' -X POST "$GROKBOT_WEBHOOK_URL" -H "Authorization: Bearer $GROKBOT_WEBHOOK_KEY" -H 'Content-Type: application/json' --data "$payload")
echo "HTTP $code $(head -c 200 /tmp/grokbot_post_resp.$$ | sed 's/crsr_[A-Za-z0-9]*/[key]/g')"; rm -f /tmp/grokbot_post_resp.$$
[ "$code" = 200 ]
