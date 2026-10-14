#!/bin/bash
# Deploy the current git HEAD to the prod VM (usersim-grokbot-web) through its watched GCS tarball.
# Refuses while any study or Browserbase session is running unless FORCE=1.
# Needs gcloud authenticated as a service account that can write the deploy bucket and SSH over IAP.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
BUCKET=gs://usersim-bakeoff-347838016394/deploy
BASE=${USERSIM_BASE:-https://atelier-sim.com}
sha=$(git rev-parse --short HEAD)
[ -z "$(git status --porcelain -- mvp src api)" ] || { echo "uncommitted changes in mvp/src/api"; exit 1; }

busy=$(curl -s -m 30 "$BASE/api/runtime/status" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('local_studies_running',0)+d.get('browserbase_running',0))")
if [ "$busy" != "0" ] && [ "${FORCE:-0}" != "1" ]; then echo "busy ($busy running); set FORCE=1 to deploy anyway"; exit 2; fi

stage=$(mktemp -d); chmod 755 "$stage"
git archive HEAD api mvp pyproject.toml requirements-vercel.txt results scripts src vercel.json | tar -x -C "$stage"
echo "$sha $(date -u +%FT%TZ) $(git rev-parse --abbrev-ref HEAD)" > "$stage/mvp/static/build.txt"
tar -czf "$stage.tgz" -C "$stage" .

ssh_vm() { gcloud compute ssh agent@usersim-grokbot-web --zone us-central1-a --tunnel-through-iap --quiet --command "$1" 2>/dev/null; }
ssh_vm "sudo sed -i 's/^USERSIM_ENGINE_VERSION=.*/USERSIM_ENGINE_VERSION=$sha/' /etc/usersim/env; grep -q ^USERSIM_ENGINE_VERSION= /etc/usersim/env || echo USERSIM_ENGINE_VERSION=$sha | sudo tee -a /etc/usersim/env >/dev/null"
gcloud storage cp "$BUCKET/usersim-grokbot.tgz" "$BUCKET/rollback/usersim-grokbot-before-$sha.tgz" >/dev/null 2>&1 || true
gcloud storage cp "$stage.tgz" "$BUCKET/usersim-grokbot.tgz" >/dev/null 2>&1
echo "uploaded $sha; waiting for $BASE/health"
for i in $(seq 1 120); do  # deploy.sh on the VM waits up to 9 min for running studies
  curl -s -m 10 "$BASE/health" | grep -q "\"$sha\"" && { echo "live: $(curl -s -m 10 $BASE/health)"; break; }
  sleep 10
done
code=$(curl -s -m 20 -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" -d '{}' "$BASE/mcp")
echo "mcp without token -> $code (want 401)"
rm -rf "$stage" "$stage.tgz"
