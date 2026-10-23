# MCP server configuration (`limits.json`)

Any agent (or human) may change **any** runtime setting on the public UserSim MCP server by opening a pull request that edits **[`mvp/sim_mcp/limits.json`](../../mvp/sim_mcp/limits.json)** on `main`. **No approval from Grok Bot, the founder, or anyone else is required** — merge the PR and the change goes live.

- **No env vars** on the server are needed for these settings (optional `MVP_MCP_<KEY>` overrides exist for emergencies on one host only).
- **No redeploy** is needed: the running server hot-reloads this file from GitHub `main` every `refresh_s` seconds (default 300, ~5 minutes; GitHub raw caching can add a few minutes).
- **No special server access**: edit the file in git; production reads `https://raw.githubusercontent.com/ShreyasPatel031/UserSim/main/mvp/sim_mcp/limits.json`.

**Confirm what production is using:**

```bash
curl -s https://35-202-98-224.sslip.io/api/mcp/limits | jq .
```

The response includes effective `values`, per-key `value_sources` (`env`, the loaded GitHub URL, `bundled`, or `default`), any `env_overrides`, fetch `error`, and today's anonymous spend.

**Secrets stay in server env** (never in this file): `MVP_CAPTCHA_API_KEY`, `MVP_SMS_PHONE`, `MVP_NTFY_SMS_TOPIC`, `GMAIL_USER`, Gmail app password, `APIFY_TOKEN`, bearer tokens (`MVP_MCP_TOKEN` / `MVP_MCP_TOKEN_FILE`), etc.

## Code deploys vs config changes

| Change | How it goes live |
|--------|------------------|
| Edit `mvp/sim_mcp/limits.json` | Hot-reload within ~5 min (no deploy). |
| Change Python under `mvp/sim_mcp/` (or other server code) | Merge to `main` → VM **pull-deploy timer** (~3 min). See [OPERATIONS.md](OPERATIONS.md). |

Config-only PRs never need a restart. Code merges do not need GitHub Actions or human `gcloud` deploy if `usersim-pull-deploy.timer` is installed (`mvp/deploy/bootstrap_vm.sh`).

## Every setting in `limits.json`

Each row has a `value` (read at **use time** so hot reload applies without restart) and an `about` line (cost/risk). Optional per-server override: `MVP_MCP_<KEY_IN_UPPER_SNAKE>`.

| Key | Default | What it does |
|-----|---------|--------------|
| `refresh_s` | `300` | How often the server re-fetches this file from `main` (min 30). |
| `allow_anonymous` | `true` | `false` = kill switch: only bearer-token callers reach `/mcp`. |
| `max_sessions` | `10` | Max open browser sessions server-wide (all callers). ↑ cost/RAM. |
| `max_per_client` | `8` | Max open sessions per IP for token callers. |
| `anon_max_concurrent_sessions_per_ip` | `3` | Max open sessions per IP without a token. |
| `max_steps` | `90` | Max browser steps per session (Brevo/ClickUp signups used ~24–25 steps alone). ↑ Browserbase + model cost; each step counts `est_usd_per_step` for anonymous budgets. |
| `budget_s` | `900` | Wall-clock session limit (15 min). |
| `idle_s` | `300` | Close session after this many seconds without a tool call. |
| `max_cells` | `108` | Max runs per study (108 = full e2e 6×6×3). |
| `wait_max_s` | `50` | Max seconds per wait-tool call (mail/SMS); agents should retry. |
| `paid_captcha` | `false` | **Master** paid CapSolver switch (~$0.002–0.01/solve when on). Needs API key in env. Token callers still need host allowlist in `captcha_spend.py` env. |
| `study_shared_accounts` | `true` | One signup per site per study; other cells of the study log in to that account (`false` = every cell signs up). |
| `paid_captcha_max_tries` | `6` | Paid tokens an `usersim_act` presolve or an open image grid may buy per session (was fixed at 2). |
| `paid_captcha_max_solves` | `6` | CapSolver createTask calls per session in the ledger (was fixed at 3). Per-site $1.50 and total $15 caps still apply. |
| `captcha_max_calls_per_page` | `6` | `usersim_solve_captcha` calls per URL before it refuses (was fixed at 3). |
| `captcha_stuck_steps` | `12` | Steps with an image grid still open before the agent is told to finish `blocked`; refused at twice this. `0` = off. |
| `probe_sites` | `true` | TLS/DNS check before opening a product URL. `false` = faster, may waste browsers. |
| `bb_proxies` | `true` | Browserbase residential proxies (better signups, higher cost). |
| `anon_daily_usd_per_ip` | `6.0` | Estimated $ budget per IP per day (no token). |
| `anon_daily_usd_global` | `20.0` | Estimated $ budget for all anonymous callers per day. |
| `est_usd_per_session` | `0.10` | Budget units charged at session start (estimate, not metered). |
| `est_usd_per_step` | `0.01` | Budget units per step (estimate). |
| `est_usd_per_prediction` | `0.60` | Budget units per successful `usersim_predict_experience`. |
| `anon_max_cells_per_study` | `12` | Max cells per study without a token (use a token for 108). |
| `anon_allow_sms` | `true` | SMS tools without a token (lease + denylist protect the real phone). |
| `sms_lease_s` | `600` | Seconds one session holds the shared SMS number. |
| `anon_daily_sms_leases_per_ip` | `10` | SMS leases per IP per day (no token). |
| `sms_sender_denylist` | list | Sender/body words never returned (protects owner's Apple/bank 2FA). |
| `anon_allow_paid_captcha` | `false` | If `paid_captcha` is true: allow **anonymous** callers to trigger paid solves. **Cost:** each solve billed to CapSolver. **Risk:** abuse burns balance. |
| `anon_allow_shared_aliases` | `false` | Allow `no_plus` / plain shared Gmail addresses without a token. **Risk:** dot-alias/plain addresses can repeat; **another anonymous caller could read the same inbox and steal verification codes**. Keep `false` unless you accept that. |

## Tests

After editing the file:

```bash
python -m pytest mvp/test_sim_mcp_limits.py -q
```

## Related docs

- [OPERATIONS.md](OPERATIONS.md) — deploy on merge, Secret Manager, `/health`, rollback
- [docs/mcp/README.md](README.md) — MCP tools and workflows for client agents
- [docs/E2E_TEST.md](../E2E_TEST.md) — full 108-cell study definition
