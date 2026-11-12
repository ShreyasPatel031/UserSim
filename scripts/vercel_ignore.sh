#!/bin/bash
# Vercel "Ignored Build Step", called from vercel.json (ignoreCommand: "bash scripts/vercel_ignore.sh").
# Exit 0 = skip this deployment, exit 1 = build. Anything unexpected must mean build, never skip.
#  - production always builds
#  - the first deployment of a branch (no VERCEL_GIT_PREVIOUS_SHA) builds
#  - otherwise skip only if nothing the app deploys changed since the branch's last successful deployment
# Paths: api/index.py imports mvp.server (src on the path); public/ is served; the rest are build inputs. data/, results/, third_party/,
# most scripts/ and *.md are already excluded by .vercelignore, and scripts/ is only used by tests.
# This script is in its own list on purpose: an edit to it must build a preview, or a broken edit would only show up on the next app change.
say() { echo "vercel_ignore: $*" >&2; }   # shows up under "Running bash scripts/vercel_ignore.sh" in the deployment log
[ "$VERCEL_ENV" = production ] && { say "production: building"; exit 1; }
[ -z "$VERCEL_GIT_PREVIOUS_SHA" ] && { say "no VERCEL_GIT_PREVIOUS_SHA (first deployment of this branch): building"; exit 1; }
# .vercelignore must not list .git: Vercel deletes ignored files BEFORE this step runs (Nov 3: "Not a git repository" -> built every time)
git rev-parse --git-dir >/dev/null 2>&1 || { say "no git repository here (is .git listed in .vercelignore?): building"; exit 1; }
git cat-file -e "$VERCEL_GIT_PREVIOUS_SHA^{commit}" 2>/dev/null || { say "last deployed commit ${VERCEL_GIT_PREVIOUS_SHA:0:7} is not in this (shallow) clone: building"; exit 1; }
if git diff --quiet "$VERCEL_GIT_PREVIOUS_SHA" HEAD -- api mvp src public vercel.json .vercelignore requirements.txt requirements-vercel.txt pyproject.toml scripts/vercel_ignore.sh; then
  say "nothing the app deploys changed since ${VERCEL_GIT_PREVIOUS_SHA:0:7}: skipping"
  exit 0
fi
say "app files changed since ${VERCEL_GIT_PREVIOUS_SHA:0:7}: building"
exit 1
