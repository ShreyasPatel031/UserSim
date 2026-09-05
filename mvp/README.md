# UserSim MVP

Local web UI for synthetic user research: URL + segment → generated tasks → parallel persona agents → executive summary.

## Public demo

**https://usersim.vercel.app**

(Vercel snapshot mode — 2 agents, ~20–45s per study. Live Browserbase agents are local-only for now.)

## Run locally (recommended)

Same behavior as production (snapshot agents, sync POST):

```bash
./mvp/vercel_dev.sh
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000).

Uses Gemini 2.5 Flash via Vertex (`config.MODEL`). Do not set MISTRAL_API_KEY for signup.

## Full local mode (live Browserbase)

```bash
pip install -r mvp/requirements.txt
PYTHONPATH=src uvicorn mvp.server:app --reload --port 8787
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). Needs `BROWSERBASE_API_KEY` (Browserbase free tier may hit minute limits).

Blocked sites (403, WAF, empty JS shells) are retried via Browserbase. If still blocked, the study stops — no inferred fallback.

## Signed-in / signed-up agents

Every live study can provision a real product account first, then reuse that
session for every persona agent.

### Sign up for any product (step 0)

```bash
# Create an account + capture the Chrome profile
PYTHONPATH=src:. .venv/bin/python -m mvp.auto_signup --url https://linear.app

# Status table: identities, profiles, blockers
PYTHONPATH=src:. .venv/bin/python -m mvp.access_report

# Probe one URL
PYTHONPATH=src:. .venv/bin/python -m mvp.access_report --check https://linear.app
```

With `MVP_AUTO_SIGNUP=1`, `run_study` calls `ensure_product_access` before
planning: healthy profile → reuse; vault credentials → sign in; otherwise →
sign up. All subsequent agents clone the same profile via `profile_pool`.

Identity uses a Gmail plus-alias per host (`you+linear@gmail.com`) stored in
`secrets/identities.json`. Email codes are read over IMAP; SMS via macOS
Messages (default) or `MVP_SMS_BACKEND=api`; CAPTCHA via CapSolver/2Captcha
when `MVP_CAPTCHA_SOLVER=1` + `MVP_CAPTCHA_API_KEY`, else a phone push.

Hard gates (`card_required`, `sso_only`, `invite_only`, `waitlist`) stop cleanly
and are recorded on the study as `auth_blocker` — payment is out of scope.

### Sign in (existing Google / vault accounts)

Credentials live in `secrets/credentials.json` (gitignored); see
`mvp/credentials.py` for the shape.

```bash
# Sign in and capture the session (fully autonomous with a totp_secret)
PYTHONPATH=src:. .venv/bin/python -m mvp.auto_signin --url https://www.youtube.com/

# Is the captured session still good?
PYTHONPATH=src:. .venv/bin/python -m mvp.session_health https://www.youtube.com/
```

With `MVP_AUTO_SIGNIN=1`, studies probe the session first and re-sign-in
automatically when it has gone stale.

Two things worth knowing before changing this:

- Google binds session cookies to the Chrome profile, so a copied cookie jar
  reports `LOGGED_IN: false` even when every cookie is present. Only a cloned
  profile authenticates, which is what `mvp/profile_pool.py` hands each agent
  (~18 MB, ~0.2 s per clone; Chrome will not share one profile across
  processes).
- `totp_secret` is what makes sign-in unattended. Without it, 2FA falls back to
  an emailed code (needs `app_password`), a forwarded SMS, or a phone tap.

## Flow

1. User enters a public URL and customer segment.
2. (Live mode + `MVP_AUTO_SIGNUP=1`) Provision / reuse a signed-in product account.
3. Mistral generates personas and on-site tasks (from signed-in page text when available).
4. Agents run in parallel, each cloning the product profile.
5. Mistral synthesizes friction themes, strengths, and recommendations.
