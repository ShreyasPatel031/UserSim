# Open MCP, no token: deploy and live check (Oct 17, 2026)

Endpoint: `https://35-202-98-224.sslip.io/mcp`. Prod VM `usersim-grokbot-web` runs **main 028a7c6** (PR #68). `/static/build.txt` = `028a7c6 2026-10-17 19:10 PDT`.
Caps come from `mvp/sim_mcp/limits.json` on main, fetched live. PR #69 (main 8bcb236) changed `max_sessions` / `max_per_client` in the file, and the running server picked that up with no redeploy. `/api/mcp/limits` reports `source` = the raw GitHub URL on main and `env_overrides: []` (snapshot: [open-mcp-oct17/limits-live.json](open-mcp-oct17/limits-live.json)).

## 1. No-token client run (`open-mcp-oct17/verify.py`, box, no Authorization header), 19:19 PDT
```
initialize: server usersim 1.26.0 protocol 2025-11-25
tools/list: 14 tools: usersim_act, usersim_finish, usersim_finish_study, usersim_get_report, usersim_observe, usersim_open_verification_link, usersim_signup_identity, usersim_signup_phone, usersim_solve_captcha, usersim_start_session, usersim_start_study, usersim_wait_for_sms_code, usersim_wait_for_verification_code, usersim_wait_for_verification_link
start_session: session 8a14d2e5 study 0a6fc666-0ab2-40f6-a38d-496dc1bc6d22 url https://example.com/ title 'Example Domain' screenshot bytes(b64) 79832
finish: {"study_id": "0a6fc666-0ab2-40f6-a38d-496dc1bc6d22", "headline": "Evidence is thin for example.com: 1 of 1 product runs stopped on the first screen.", "proof_pass": false, "next": "Call usersim_get_report."}
observe after finish: {"error": "session is closed (finished: completed)"}
elapsed 17.1s
```
Report: https://usersim.vercel.app/report?study=0a6fc666-0ab2-40f6-a38d-496dc1bc6d22

## 2. HTTP auth checks (curl)
- `POST /mcp` initialize, no header → **200**
- `POST /mcp` with `Authorization: Bearer wrong` → **401** `{"error":"wrong bearer token (or remove the Authorization header: no token is needed)"}`
- A valid existing token is still accepted (unit test `test_right_token_reaches_mcp`). Such callers skip the anonymous caps.

## 3. Live cap rejection (`open-mcp-oct17/capcheck.py`, no token)
```
start #1: ok session 1cd512c0
start #2: ok session a6a6797e
start #3: ok session 37978761
start #4: REFUSED -> cap anon_max_concurrent_sessions_per_ip: this client IP already has 3 open browser sessions (the limit without a token); finish one with usersim_finish first
finish 1cd512c0 b1b1575b-2682-4f52-977e-17577ecf5867
finish a6a6797e cf524d17-3ddb-4b55-83c1-ae5fde877d30
finish 37978761 5c184a7d-6fa2-40a8-85e7-abb39410c21d
```
After these 4 sessions, `/api/mcp/limits` showed the estimated anonymous spend at `total_usd: 0.4` (4 × $0.10 per session start).

## 4. Unit tests (`mvp/test_sim_mcp_limits.py`, `mvp/test_sim_mcp_auth.py`): 21 passed
These cover:
- the daily $ cap per IP and in total, persisted across restarts
- refusal of `start_session` and `act` once the budget is used up
- no charge for callers with a token
- the env override, and bad values being ignored
- the refresh from main applying, with a broken remote file keeping the last good values
- `X-Forwarded-For` trusted only as the last hop from 127.0.0.1
- another IP getting `unknown session_id` for my session and inbox
- SMS, `no_plus` and plain shared addresses being refused without a token
- the paid captcha solver being off without a token
- the `allow_anonymous=false` kill switch returning 401

The full `mvp/test_sim_mcp*.py` suite gives 189 passed and 9 failed. The same 9 fail on main 8134511 before this change.

## Caps in force (limits.json)
| key | value |
|---|---|
| `allow_anonymous` | true |
| `anon_max_concurrent_sessions_per_ip` | 3 |
| `anon_daily_usd_per_ip` / `anon_daily_usd_global` | $2.00 / $10.00 per day (America/Los_Angeles), estimated |
| `est_usd_per_session` / `est_usd_per_step` | $0.10 / $0.01 (assumptions, not metered) |
| `anon_max_cells_per_study` | 12 |
| `anon_allow_sms` / `anon_allow_paid_captcha` / `anon_allow_shared_aliases` | false / false / false |
| `max_sessions` / `max_per_client` (token callers) | 10 / 8 |

## Notes
- The VM env overrides `MVP_MCP_MAX_SESSIONS=10` and `MVP_MCP_MAX_PER_CLIENT=8` were removed from the instance metadata and `/etc/usersim/env`, so the file is the only place these are set.
- `/health` still says `engine_version` 5f789ed. That label is a stale pin, `USERSIM_ENGINE_VERSION`, in `/etc/usersim/env`, and it doesn't reflect the code. The pin is now set to 028a7c6 and takes effect at the next restart; the service was not restarted, because 2 studies were running. `/static/build.txt` is the true build.
- Callers without a token are keyed by client IP. A client whose egress IP changes in the middle of a session gets `unknown session_id` for it.
