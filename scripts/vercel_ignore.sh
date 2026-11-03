#!/bin/bash
# Vercel "Ignored Build Step", called from vercel.json (ignoreCommand: "bash scripts/vercel_ignore.sh").
# Exit 0 = skip this deployment, exit 1 = build. Anything unexpected must mean build, never skip.
#  - production always builds
#  - the first deployment of a branch (no VERCEL_GIT_PREVIOUS_SHA) builds
#  - otherwise skip only if nothing the app deploys changed since the branch's last successful deployment
# Paths: api/index.py imports mvp.server (src on the path); public/ is served; the rest are build inputs. data/, results/, third_party/,
# most scripts/ and *.md are already excluded by .vercelignore, and scripts/ is only used by tests.
# This script is in its own list on purpose: an edit to it must build a preview, or a broken edit would only show up on the next app change.
[ "$VERCEL_ENV" = production ] && exit 1
[ -z "$VERCEL_GIT_PREVIOUS_SHA" ] && exit 1
if git diff --quiet "$VERCEL_GIT_PREVIOUS_SHA" HEAD -- api mvp src public vercel.json .vercelignore requirements.txt requirements-vercel.txt pyproject.toml scripts/vercel_ignore.sh; then
  exit 0
fi
exit 1
