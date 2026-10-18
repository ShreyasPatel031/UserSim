# Website driver vs MCP (mvp/sim_mcp) — discrepancy audit, Oct 7 2026

Branch audited: `claude/clever-goodall-1r9iqq` @ d1db14a. Fix branch: `mcp-signup-parity` (see PR).

## Root cause
- The MCP was **not built on the website's agent path**. Commit **458a507 (Oct 6 2026, 21:21 UTC = 2:21 PM PT)**
  "MCP MVP: a coding agent drives one simulated user on our Browserbase" added `mvp/sim_mcp/sessions.py` (682 lines):
  its own Playwright-over-Browserbase action loop (click/type/scroll/...) that reuses only the Study record,
  screenshot upload and the judge/gates. It never imports `mvp.a11y_agent` / `mvp.signup_in_session`, which is where
  every signup capability lives (signup_in_session added d09879b, Sep 26; signup_inbox, captcha, sms_provider since Sep 5).
- Why: the plan doc `docs/plans/usersim_mcp.md` scoped it out explicitly — §5 "Later phases (designed for, not built):
  test accounts / sign-up", driver hardcoded as `driver: "claude_code"` ("other models can plug in later. Not built now"),
  persona fidelity "out of scope". The MVP treated signup as a later phase, so the client model was left facing
  signup walls with only raw clicks and no inbox. d1db14a (Oct 6) added multi-cell studies on the same separate path, so the gap widened.
- Also: the MCP's URL guard whitelisted `accounts.google.com` and `github.com` as "sign-in providers" — i.e. it
  *allowed* the social sign-in that is forbidden for us.

## Capabilities the website has that MCP lacked
| # | Website capability (module) | MCP at d1db14a | Fix on mcp-signup-parity |
|---|---|---|---|
| 1 | Fresh Gmail plus-alias inbox per signup (`signup_inbox.create_inbox`) | none | `usersim_signup_identity` (via shared `mvp/signup_tools.new_signup`) |
| 2 | Identity fields: name, password, company, workspace (`signup_in_session._identity`) | none | moved to `signup_tools.identity_fields`; website imports it |
| 3 | Wait for verification code (`email_codes` / `Inbox.wait`) | none | `usersim_wait_for_verification_code` |
| 4 | Wait for verification / magic link, ranked (`signup_inbox.rank_links`) | none | `usersim_wait_for_verification_link` + `usersim_open_verification_link` |
| 5 | SMS phone + code (ntfy relay / TextVerified, `sms_provider`) | none | `usersim_signup_phone`, `usersim_wait_for_sms_code` |
| 6 | Captcha detect + solve (`captcha.detect_sitekey`, free reCAPTCHA audio, CapSolver) | none | `usersim_solve_captcha` (free audio; paid solver only if `MVP_MCP_PAID_CAPTCHA=1`) |
| 7 | Human gestures for slider / press-and-hold checks | click/type only | new actions `drag`, `press_and_hold` |
| 8 | Email-only rule (no Google/GitHub) | Google/GitHub *allowed* | blocked in navigate + auto-back if a click lands there |
| 9 | Inbox safety: only the dedicated signup account | none (tunnel had GMAIL_USER unset) | `signup_tools.assert_signup_inbox` (refuses any other inbox, personal one hash-blocked) |
| 10 | Driver = configured model | `DRIVER = "claude_code"` hardcoded | `MVP_MCP_DRIVER` env, default `mcp_client` |
| 11 | Shared session / share-key signup reuse (`signup_share`), auth_state/profile_pool reuse, auto_signin from credentials vault | none | not ported (website-study specific; we want fresh accounts) |
| 12 | Captcha spend metering (`captcha_spend`) | none | not ported (paid solver off by default) |
| 13 | Judge sees step history, not only final.png | final.png only | not in this PR |

## Shared module
`mvp/signup_tools.py` is now the one place both paths get the inbox, identity and mail waits. `signup_in_session`
(website) calls `new_signup` and `identity_fields`; the MCP tools call the same functions.

## the-old-personal-inbox scrub
Code/comments/tests scrubbed: `mvp/identity.py`, `mvp/signup_inbox.py`, `mvp/test_signup_in_session.py`,
`src/capability/voice_ai_dashboards.py` (default now `GMAIL_USER` / usersim.signups). Remaining hits are historical
result data files (`results/`, `reports/`, `mvp/bakeoff_data/`), not code; left untouched.

## Added during the signup loop (same PR)
- 14. Website driver sees an element list; MCP sent only pixels. Fixed: observations include `fields` with exact coordinates; `type` accepts x,y (42c15f8).
- 15. Judge saw final.png only. Fixed: the judge also gets server-observed signup facts, and there is a new `signup_verified` proof check (2be3f5d). The judge also counts any signed-in page reached after verification as done for signup goals (23e790c).
- 16. Identity had no username. Fixed: a unique `username` in the shared identity; added `triple_click` (bd06d30).
- 17. The free reCAPTCHA audio solver failed on already-open or invisible challenges and gave false success. Fixed in 49e1b0c and ee5d0d8.
