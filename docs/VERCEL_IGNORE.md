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

## Tests and how to check it on Vercel
- `python -m pytest scripts/test_vercel_ignore.py` runs the script in a throwaway git repository (17 cases: non-app paths skip, app paths build, production and first deploys build, errors build).
- On Vercel, a skipped deployment shows as canceled/ignored and the log has a "Running Ignored Build Step" line; a build shows the normal build log. The deployment log is the only place that proves the script ran.
