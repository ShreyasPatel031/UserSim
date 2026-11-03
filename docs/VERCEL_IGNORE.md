# Vercel: which pushes spend a deployment

`vercel.json` has `"ignoreCommand": "bash scripts/vercel_ignore.sh"`. The free plan allows 100 deployments a day, and before this rule every push to any PR branch spent one,
so docs and experiment PRs hit the limit ("Deployment rate limited - retry in 24 hours", code `api-deployments-free-per-day`) and blocked each other.

## The rule (`scripts/vercel_ignore.sh`; exit 0 = skip, exit 1 = build)
- Production always builds.
- The first deployment of a branch builds (Vercel sets no `VERCEL_GIT_PREVIOUS_SHA` yet).
- Otherwise the deployment is skipped only when none of `api mvp src public vercel.json .vercelignore requirements.txt requirements-vercel.txt pyproject.toml scripts/vercel_ignore.sh`
  changed since the branch's last *successful* deployment. A failed or rate-limited deployment is not that baseline, and a multi-commit push is compared as a whole.
- Any error (unknown SHA, shallow clone, missing file) exits 1, which builds. A wrong guess therefore costs a deployment, never a missing one.

## Limits and gotchas
- `ignoreCommand` may not be longer than **256 characters**; Vercel rejects the whole deployment before any build otherwise. That is why the logic lives in the script.
- Keep the path list in step with what the app imports (`api/index.py` imports `mvp.server`, with `src` on the path). If the app starts using a new top-level directory, add it to the list,
  or changes there will be skipped. `data/`, `results/`, `third_party/` and `*.md` are already excluded from the deployment by `.vercelignore`.
- The first push of every new branch still builds once.

## Why the first versions never skipped (found from the deployment log, Nov 3)
- Version 1's command was 272 characters: rejected before any build ("`ignoreCommand` should NOT be longer than 256 characters").
- Version 2 ran, but `.vercelignore` listed `.git`, and Vercel deletes ignored files **before** it runs the ignore command, so `git diff` died with "Not a git repository", the script fell through to "build", and every push built.
- Fix: `.git` is no longer in `.vercelignore`, so the ignore step can see history; and `.git` is excluded from the function bundle instead (`functions."api/index.py".excludeFiles` is `{public,.git}/**`).
  This pair matters: `.git` is about 265 MB here and a function bundle is limited to about 250 MB, so a bundled `.git` would fail a deployment. `test_vercelignore_keeps_git_for_the_ignore_step_and_the_function_excludes_it` fails if either half is undone.
- The clone Vercel makes is shallow. If the last deployed commit is not in it, the script builds and says so (`vercel_ignore: last deployed commit ... is not in this (shallow) clone`).

## Verified on Vercel (Nov 3, preview of PR #145)
- Deployment `Bym9EN142`: the log shows `Running "bash scripts/vercel_ignore.sh"`, then `vercel_ignore: app files changed since 226d7dc: building`, then `Running "vercel build"`. So `.git` and the previous deployed commit were present in Vercel's clone, the diff worked, and the build ran for the right reason (`vercel.json`, `.vercelignore` and the script had changed). The 265 MB `.git` did not break the function bundle (Ready in about 37 s).
- A docs-only push after that should show `vercel_ignore: nothing the app deploys changed since ...: skipping` and a canceled deployment. The result of that test is recorded in PR #145.

## Tests and how to check it on Vercel
- `python -m pytest scripts/test_vercel_ignore.py` runs the script in a throwaway git repository (21 cases: non-app paths skip, app paths build, production and first deploys build, every error builds with a reason).
- On Vercel, a skipped deployment shows as canceled/ignored and the log has a "Running Ignored Build Step" line; a build shows the normal build log. The script prints one line starting `vercel_ignore:` saying why it built or skipped; the deployment log is the only place that proves it ran.
