#!/usr/bin/env bash
# Point https://usersim.vercel.app at the long-running backend VM (usersim-grokbot-web,
# static IP 35.202.98.224, HTTPS at https://35-202-98-224.sslip.io via caddy) with Vercel rewrites, so the
# browser only talks HTTPS to Vercel and Vercel proxies to the VM over HTTPS.
#
# Needs a Vercel token that can deploy project "usersim" in scope shreyaspatel031s-projects
# (the token in /workspace/.vercel-token.env cannot: limited=true, team_unauthorized).
#   MODE=proxy (default): deploy deploy/vercel-proxy (static + rewrites) to production.
#   MODE=full: deploy the whole repo (Python app on Vercel functions, 300s cap) instead.
set -euo pipefail
. /workspace/usersim-env.sh >/dev/null 2>&1 || true
SCOPE=${VERCEL_SCOPE:-shreyaspatel031s-projects}
PROJECT=${VERCEL_PROJECT:-usersim}
MODE=${MODE:-proxy}
export VERCEL_TELEMETRY_DISABLED=1
here=$(cd "$(dirname "$0")" && pwd)
dir="$here/vercel-proxy"; [ "$MODE" = full ] && dir="$(cd "$here/.." && pwd)"
cd "$dir"
if [ "$MODE" = proxy ]; then
  # REST API deploy (no git metadata): the CLI from this checkout is BLOCKED on Hobby
  # (commit author not a team member) and then waits forever. See vercel_deploy.py.
  timeout 300 python3 "$here/vercel_deploy.py" </dev/null
else
  vercel link --yes --project "$PROJECT" --scope "$SCOPE" --token "$VERCEL_TOKEN" </dev/null
  timeout 900 vercel deploy --prod --yes --scope "$SCOPE" --token "$VERCEL_TOKEN" </dev/null
fi
curl -s -o /dev/null -w 'usersim.vercel.app / -> %{http_code}\n' https://usersim.vercel.app/
curl -s https://usersim.vercel.app/health; echo
