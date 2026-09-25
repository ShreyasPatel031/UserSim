# Voice dashboard logged-in traces

Logged-in Retell / Vapi / Bland dashboard bakeoff traces feeding the Retell study.
Branch off `#39` (`cursor/e2e-plus-signup-12d9`). Fresh Sign Up test aliases; no passwords/cookies committed.

Generated: 2026-09-25T11:35:08.600895+00:00

## What ran

- **Signup**: sequential Browserbase sessions tagged `owner=report` for Retell, Vapi, Bland.
- **Dashboard tasks**: 3 personas (Platform Engineer, Product Manager, Startup Founder)
  × 5 shared tasks × 3 platforms = 45 runs via bakeoff `browser_use` harness.
- **Budget**: ~40 steps / ~8 min wall per run.
- **Constraints**: no live calls, no number purchases, no credit spend, no key create/delete.

## Signup outcomes

| Product | ok | reason | captcha friction |
|---------|----|--------|------------------|
| retell | False | captcha_unsolved | True |
| vapi | True | signed_up | False |
| bland | False | phone_required | False |

## Task outcomes (per product)

- **retell**: 0/15 success, 0 product fails, 15 harness fails
- **vapi**: 11/15 success, 3 product fails, 1 harness fails
- **bland**: 0/15 success, 0 product fails, 15 harness fails

## Branch

`cursor/voice-dashboard-traces-12d9` (off `#39` / `cursor/e2e-plus-signup-12d9`).

## Blockers

- **Retell**: signup blocked by reCAPTCHA (recorded as friction).
- **Bland**: signup requires phone; SMS provider unavailable (recorded as friction).
- **Retell/Bland dashboard tasks**: all HARNESS failures (no authenticated session).
- **Vapi**: 11/15 success; 3 PRODUCT fails on API keys/webhooks (landed on org settings); 1 HARNESS (session drop to login on founder system-prompt).

## Artifacts

- `mvp/bakeoff_data/voice_dashboard_*.json` — bakeoff manifests
- `mvp/bakeoff_data/prebaked/voice_dashboard_browser_use_all_v1.json` — study + per-step traces
- `public/bakeoff-traces/bu_*` — screenshots (no cookies/passwords)

