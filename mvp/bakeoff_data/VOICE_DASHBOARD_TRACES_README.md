# Voice dashboard logged-in traces

Logged-in Retell / Vapi / Bland dashboard bakeoff traces feeding the Retell study (PR #37).
Branch off `#39` (`cursor/e2e-plus-signup-12d9`). Fresh Sign Up test aliases; **no passwords/cookies committed**.

## Status (in progress)

Signups (Browserbase `owner=report`, one session at a time):

| Product | Outcome | Finding |
|---------|---------|---------|
| Retell | blocked | `signup_captcha_friction` (reCAPTCHA unsolved) |
| Vapi | signed up | — (alias `+vapivd`, name Jordan Ellis) |
| Bland | blocked | `signup_phone_required` (SMS unavailable) |

Dashboard runs (3 personas × 5 tasks × 3 platforms) via bakeoff `browser_use` harness follow; manifests land in this directory.

## Constraints

No live calls, no number purchases, no credit spend, no API key create/delete.
