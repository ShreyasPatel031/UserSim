# UserSim MCP server: guide for agents

## For client agents

Connect to **`https://35-202-98-224.sslip.io/mcp`** with **no token** and **no env vars**.

Do **not** set `MVP_OWNER_PHONE`, `MVP_NTFY_SMS_TOPIC`, `GMAIL_USER`, `MVP_CAPTCHA_API_KEY`, `APIFY_TOKEN`, or `credentials.json`, and do **not** run the UserSim engine locally. The server owns:

- **SMS** — `usersim_signup_phone` / `usersim_wait_for_sms_code` (shared lease on the host phone)
- **Signup inbox** — `usersim_signup_identity` / `usersim_wait_for_verification_code` / `usersim_wait_for_verification_link`
- **Competitor finding** — when you omit rival URLs on `usersim_start_study`
- **Captcha** — the run stops and reports; no paid solver unless the founder approves it

Accounts are always **fresh signups** on `usersim.signups+<tag>@gmail.com` aliases. To log in on a later cell or after a redirect, reuse a prior MCP-created account with `same_account_as`. Never use personal logins.

**E2e test definition (full study only):** [docs/E2E_TEST.md](../E2E_TEST.md) — target + 2 competitors, 6 personas, 6 tasks, 108 cells, comparison report. Reduced studies are rejected.

Source of truth: `mvp/sim_mcp/server.py`, `mvp/sim_mcp/sessions.py`, `mvp/sim_mcp/report.py`, `mvp/sim_mcp/limits.py` / `limits.json` on `main`. If this guide and the code disagree, the code wins. A live server also describes itself: call `list_tools` and read the server `instructions`.

## Two modes

- **Human mode** (everything below except `usersim_predict_experience`): a simulated user really uses the product in
  a recorded cloud browser, and UserSim judges it.
- **Agent mode** (`usersim_predict_experience`): no browser. Predicts how a kind of user will experience a product from
  live G2, Capterra, TrustRadius and Gartner reviews of the product and its named rivals. Returns expected ratings, pros, cons and the overall experience.
  Use it to set expectations before human mode, or when a browser run isn't possible.
- **Human mode on top of agent mode** (`usersim_plan_human_run` → a browser run → `usersim_combine_human_run`): the
  run is given the task that adds signal, and what it saw is added to the agent-mode prediction in the amount that
  held up on real reviewers. See [Human mode on top of agent mode](#human-mode-on-top-of-agent-mode).

## What it does

UserSim lets an AI agent act as a **simulated user** of a real, public web product, inside a real cloud browser (Browserbase) that UserSim runs and records. The calling model *is* the simulated user: it looks at screenshots and sends one action at a time (`usersim_act`). UserSim records every step, screenshot and first-person `thought`. When the session ends, UserSim runs its own independent judge and proof checks and writes a report. The report is the same one the UserSim website produces. A **study** is always the full e2e matrix ([docs/E2E_TEST.md](../E2E_TEST.md)): your product plus **2** competitors, **6** personas, **6** tasks, **108** scored cells, and the comparison report. Signup tools give the simulated user a real email inbox, so it can complete email-verified signups.

## Connecting (no token needed)

The whole setup is one URL:

```
https://35-202-98-224.sslip.io/mcp
```

No token, no env file, no tunnel. Since Oct 17, 2026 the endpoint is open to anyone who has the URL. Callers without a token get the caps in [Limits](#limits). (`usersim.vercel.app/mcp` and `atelier-sim.com/mcp` still return 404 until the Vercel `/mcp` rewrite is deployed; use the URL above.)

| | |
|---|---|
| Transport | MCP **streamable HTTP**, stateless, JSON responses |
| URL | `https://35-202-98-224.sslip.io/mcp` (methods GET, POST, DELETE) |
| Auth | None. An optional `Authorization: Bearer <token>` still works for existing clients, and a valid token skips the anonymous caps. A **wrong** token gets **401** (remove the header instead) |
| Who owns what | Without a token, the `session_id` is your credential: it is random, returned only to you, and works even if your IP changes between calls (NAT, Cloudflare WARP, iCloud Private Relay, cloud-agent egress pools). Keep it private. Study ids are public (they're in watch links), so any caller without a token who has a study id can run its queued cells. Token callers only see what their own token created. The inbox tools only return mail for the alias your own session created. Caps are still counted per client IP |

### Claude Code
```bash
claude mcp add --transport http usersim https://35-202-98-224.sslip.io/mcp
```

### Claude Desktop (`claude_desktop_config.json`, via the `mcp-remote` bridge)
```json
{
  "mcpServers": {
    "usersim": { "command": "npx", "args": ["-y", "mcp-remote", "https://35-202-98-224.sslip.io/mcp"] }
  }
}
```

### Cursor (`~/.cursor/mcp.json` or `.cursor/mcp.json`)
```json
{
  "mcpServers": {
    "usersim": { "url": "https://35-202-98-224.sslip.io/mcp" }
  }
}
```

### Python (official `mcp` SDK)
```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "https://35-202-98-224.sslip.io/mcp"

async def main():
    async with streamablehttp_client(URL, timeout=300) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print([t.name for t in (await s.list_tools()).tools])
            res = await s.call_tool("usersim_start_session", {
                "product_url": "https://example.com",
                "persona": "Priya, a freelance designer who has never used this tool.",
                "task": "Find out what this site is for."})
            for c in res.content:          # text = JSON metadata, image = JPEG screenshot (base64)
                print(c.type, c.text[:400] if c.type == "text" else len(c.data))

asyncio.run(main())
```
`python -m mvp.e2e_mcp --base https://35-202-98-224.sslip.io` runs the built-in smoke test (no token needed).

### Running the server (operators)
The prod copy runs on the VM `usersim-grokbot-web` (uvicorn :80 behind caddy on :443). It redeploys itself within about 20 s of a new app tarball in GCS (`/workspace/deploy/push_from.sh`). Run uvicorn with **one worker**, because MCP sessions live in process memory. `MVP_MCP_TOKEN` / `MVP_MCP_TOKEN_FILE` are optional now: they only define tokens that skip the anonymous caps.

## Response conventions

- Every tool returns either a **JSON string** or **[JSON string, JPEG image]** (observation tools).
- Errors are **not** MCP protocol errors. They come back as a normal result `{"error": "<message>"}`, so always check for an `error` key.
- **Coordinates** are pixels in the **1280×800** screenshot (`sessions.VIEWPORT`). x,y outside it are rejected.

### Observation object (start_session, observe, act, open_verification_link, solve_captcha)
JSON fields: `session_id`, `step`, `url`, `title`, `steps_left`, `seconds_left`, and, when present:
- `fields`: visible form fields (kind, label, exact x,y, filled/checked, options for dropdowns). Use these coordinates.
- `unfilled_fields`: empty text-like fields in a half-filled form (up to 6)
- `hidden_fields`: fields that can't be clicked (invisible, covered, off-screen or a bot trap)
- `page_errors`: inline form errors and JS/console errors
- `note`: for example, a click that only jumped to an in-page anchor
- `email_hint`: the site rejected a `+` alias, so follow the hint
- `captcha`: captcha state plus a `hint` that tells you what to do next
- `action_error`: your last action failed, and this says why
- `captcha_presolve`: only when the server's paid solver ran before a click

The image that follows is the JPEG screenshot.

## Tools

### Core session tools

#### `usersim_start_session`
| param | type | default | notes |
|---|---|---|---|
| `product_url` | string | "" | Public http(s) URL. localhost, `.local`/`.internal` and private IPs are rejected. Scheme defaults to https |
| `task` | string | "" | One goal, in the persona's words. Required when you're not in a study |
| `persona` | string | "" | One or two sentences: who they are, what they know, why they're here. Required when you're not in a study |
| `study_id` | string | "" | Study mode: pass only `study_id` and `cell_id` |
| `cell_id` | string | "" | Comes from `usersim_start_study` |

Returns an observation plus `study_id`, `cell_id`, `persona`, `task`, `site`, `watch_url` (live view, `https://usersim.vercel.app/?study=<id>`), `rules` (`max_steps`, budget, `idle_timeout_s`, …), `engine_version` and `next`. A standalone session is saved as a one-run study, so `study_id` is what you pass to `get_report`.
```json
{"product_url":"https://example.com","persona":"Sam, an ops lead evaluating uptime tools.","task":"Create an account and add one monitor."}
```

#### `usersim_observe`
`session_id: string`. Returns an observation without acting.

#### `usersim_act`
| param | type | notes |
|---|---|---|
| `session_id` | string | |
| `action` | object | Exactly one action, see below |
| `thought` | string | Required. A short first-person note on what you see, expect, or find confusing. This is recorded as research data |

Action types (`sessions.ACTION_TYPES`):
- `{"type":"click","x":..,"y":..}`, `double_click`, `triple_click` (selects the field's text), `right_click`, `hover`
- `{"type":"type","text":"...","x":..,"y":..,"submit":false}` clicks the field at x,y, clears it and types. Leave out x,y to type into the focused field. Text is capped at 2000 characters.
- `{"type":"key","keys":"Enter"}` (also `Tab`, `Escape`, `Control+A`, …)
- `{"type":"scroll","dy":600,"x":..,"y":..}` (dy>0 scrolls down; dy must be an integer)
- `{"type":"back"}`, `{"type":"reload"}`, `{"type":"clear_cookies"}` (logs out: clears cookies and site storage, then reloads), `{"type":"wait","ms":1000}`
- `{"type":"navigate","url":"..."}` works on the **product's own site only**
- `{"type":"select","x":..,"y":..,"option":"visible text","field":"dropdown label"}` works with native or custom dropdowns. Native popups never show in screenshots, so pick from the `options` listed under `fields`. `field` is optional.
- `{"type":"press_and_hold","x":..,"y":..,"ms":4000}` (press-and-hold checks)
- `{"type":"drag","x":..,"y":..,"to_x":..,"to_y":..}` (sliders and puzzle captchas)

Returns the new observation. Google/GitHub sign-in hosts are blocked. If the page wanders onto a mail provider or a third-party account site, UserSim returns to the product and reports an `action_error`.
```json
{"session_id":"…","action":{"type":"click","x":640,"y":412},"thought":"The big 'Start free' button looks like the way in."}
```

#### `usersim_finish`
`session_id: string`, `outcome: string` (`completed` | `gave_up` | `blocked`), `notes: string` (what was easy or hard, and why you stopped). This closes the browser and runs the judge and proof checks.
Returns `{study_id, headline, proof_pass, next}` for a standalone session, or `{study_id, cell_id, goal_reached, proof_pass, study_phase, next}` for a study cell.

#### `usersim_get_report`
`study_id: string`, `format: string = "markdown"` (or `"json"`). The report covers the independent judge verdict, proof checks, friction, and every step with screenshot links. It works for live studies and for saved ones (loaded from local storage or GCS). If the study isn't finished yet, the report includes a `note`. For studies, call again in about 30 s.

### Study tools

#### `usersim_start_study`
| param | type | notes |
|---|---|---|
| `product_url` | string | Public URL |
| `personas` | list[object] | `[{"name":"Maya Ortiz","bio":"…","favors":"<site URL or name, optional>"}]`. `bio` is required |
| `tasks` | list[object] | `[{"prompt":"one goal in the user's words","favors":"<optional>"}]`. `prompt` is required |
| `competitors` | list[string] \| null | Exactly **2** public URLs, or omit/`[]` to auto-discover. A competitor can't be the same site as the product |

Required shape: **6** personas, **6** tasks, **2** competitors (108 cells). Wrong partial counts are rejected with a pointer to `docs/E2E_TEST.md`. Anonymous callers are still capped by `anon_max_cells_per_study` in `limits.json` (default 12 without a token — use a bearer token for a full 108-cell study).
Returns `{study_id, watch_url, report_url, runs, cells:[…], rules:{max_steps, budget_s, idle_timeout_s, max_parallel}, next}`.

#### `usersim_finish_study`
`study_id: string`. This writes the report now from the cells that ran, and marks cells that never started as skipped. Finish any running cells first. Returns `{study_id, started, status, phase, next}`.

### Agent mode tool

#### `usersim_predict_experience`
| param | type | notes |
| --- | --- | --- |
| `product` | string | Name as review sites list it, e.g. `"Basecamp"`. The scrapers search by this name. |
| `persona` | object | `role` (required); `company_size`, `industry`, `time_used` (`"trial"`, `"<6 months"`, `"6-12 months"`, `"1-2 years"`, `"2+ years"`) and `bio` are optional. |
| `product_url` | string | Strongly recommended. A model checks that the scraped reviews are of the product at this URL and not another product with the same name. Without it, the product's own reviews are not used. |
| `task` | string | Optional: what this user is trying to get done. |
| `competitors` | string[] | 1–3 real rival names. They set the rating prior and the complaint topics. Omit them to discover rivals from `product_url` with the study planner; `evidence.rivals_source` says which. |

The first call starts live scrapes of the product and its rivals (Apify; 1–2 min) and returns `status: "pending"`. Call
again with the same arguments. Other statuses: `ok`, `no_data` (with `reason`, e.g. no reviews found or no
`APIFY_TOKEN` on the server; nothing is substituted), `disabled`.

What you get on `ok`:

- **`ratings`**: `overall_rating`, `ease_of_use_rating` and `recommendation_score`, each with `estimate`, `basis`,
  `n_own`, `n_rivals`, `own_mean` and `rivals_mean`. The estimate is the product's last 100 own reviews, shrunk toward
  its rivals' average with k = 10. With no own reviews, it is the rivals' average.
  - **`most_likely`** is the single likeliest whole score (`for_this_persona` − 0.25, rounded up). Use it when one
    number is wanted. Ratings skew to the top, so the likeliest score sits above the average (held-out MAE 0.55).
  - **`for_this_persona`** adds small within-product offsets for the persona's role, company size, `time_used` and
    industry; `persona_offsets` lists the ones applied. Time using the product matters most: a first-time
    (`"trial"`) user recommends about 0.5 points lower than the product's average.
  - On held-out reviewers the offsets raised per-person ranking within a product (recommend Spearman 0.00 → 0.13) and
    cut error on 6 of 7 test sets.
  - Evidence: `experiments/human_experience/heldout_bench.py` and `personalize.py`.
- **`pros`**, **`cons`** and **`overall_experience`**: written by the held-out-validated predictor prompt. Its evidence:
  people-like-this-persona averages (`mvp/agent_mode_segments.json`), the rivals' ratings and complaint topics, and the most
  similar reviewers of the product and its rivals.
- **`evidence`**: how many reviews were used, which rivals had none, and scraper errors.
  - `own_reviews_check` and `rivals_check` record the identity gate. A model checks that the own reviews are of this
    product, and that each rival's reviews are of that rival and it is a direct or partial competitor.
  - Anything that fails, or can't be checked, is left out, and the reason is given. `rivals_used` lists the rivals that passed.
  - The gate was added after the YC test, where a startup named "Dock" pulled in reviews of Dock Health, and the planner
    named rivals that do a different job.

Callers without a token are charged `est_usd_per_prediction` against the daily caps, only when a call returns `ok`.

### Human mode on top of agent mode

Use these when you want a prediction (like `usersim_predict_experience`) that also uses first-hand evidence from a
simulated user's session in the product.

#### `usersim_plan_human_run`
| param | type | notes |
| --- | --- | --- |
| `product` | string | Name as review sites list it. |
| `product_url` | string | Public URL of the product (required). |
| `persona` | string | One sentence: who the simulated user is. |
| `competitors` | string[] | 1–3 rival names; omit to discover them from `product_url`. |

Returns `start_session` (`product_url`, `persona`, `task`) for `usersim_start_session`, plus `observe`: the format
for the run's observations. The task is built from the rivals' live review complaints. It asks for the core job done
for real with 3+ items, then two second-level features (views, custom fields, reports, automations...), then
editing or reorganising. It skips onboarding and pricing, because review data already predicts those
(`experiments/staged_context/out/human_mode/themes.csv`). `status: "pending"` while rival scrapes run.

#### `usersim_combine_human_run`
| param | type | notes |
| --- | --- | --- |
| `product`, `persona`, `product_url`, `task`, `competitors` | | As for `usersim_predict_experience`. |
| `observations` | object[] | The run's `[{"kind": "product_friction" \| "product_benefit" \| "signup_friction" \| "agent_failure", "what": "..."}]`. Only `product_*` ones are used. |

Returns the agent-mode result with `mode: "human"`, the agent-mode words under `agent_mode`, `observations_used` and
`rule`:

- **Ratings:** always agent mode's. A first session's impressions ran about a star below real reviewers.
- **Product with its own reviews:** pros, cons and the overall experience are rewritten from agent mode's evidence
  plus the run's product observations. Held out on 173 real reviewers of 5 products, cons recall rose by
  0.046 (95% CI +0.007 to +0.085) and pros were unchanged. Evidence: `experiments/staged_context/hm_agent_eval.py`.
- **No own reviews (a new product):** at most one pro and one con change. Notes about setup, free-plan limits,
  onboarding, pricing, billing and support are dropped first. On 5 products this raised cons recall by 0.033
  (95% CI +0.001 to +0.066), while free-form notes lowered both pros and cons.

Sign-up is the main limit for callers without a token: 6 of 12 test runs were blocked. Sites rejected `+` email
aliases, showed image CAPTCHAs, required a phone, or had no free plan.

### Signup and inbox tools

| tool | params | returns |
|---|---|---|
| `usersim_signup_identity` | `session_id`, `no_plus: bool = false`, `same_account_as: str = ""` | A fresh email alias plus password, name and username. It's the same identity for the whole session. If you call it again, you get the same one with a `next` warning, and after 3 repeats an `error`. `no_plus=true` returns a fresh **dot-variant** of the same Gmail inbox (for sites that reject `+`) and replaces the alias. `same_account_as=<earlier session_id>` returns the account that earlier session (yours, same site) created, so a later study cell can **log in** instead of signing up again; login codes/magic links mailed to it are readable with the wait tools in the new session (only mail that arrives after the call). That run is not judged as a signup. This works after a server restart too: the server keeps the signup account on its own disk outside the app directory, so deploys keep it too (`/var/lib/usersim/mcp_accounts`, mode 600, keyed by a hash of the session_id, 30 days) |
| `usersim_wait_for_verification_code` | `session_id`, `timeout_s: int = 120` (clamped to 10–240) | `{found, subject, sender, code, links, link_texts}` or `{found:false, note}` |
| `usersim_wait_for_verification_link` | `session_id`, `timeout_s: int = 120` (10–240) | Same shape, with links ordered best first. Links from earlier mails stay openable |
| `usersim_open_verification_link` | `session_id`, `url`, `thought` (default "I click the link in the email.") | Opens the link in the session browser and returns an observation. Only URLs returned by the wait tool are accepted, and each one opens only once. The redirect chain is recorded, so click-tracking redirects are fine |
| `usersim_signup_phone` | `session_id` | `{phone, lease_seconds_left, lease}`. Use it only if a site insists on SMS. The number is shared, so it is leased to one session at a time (`sms_lease_s`, about 10 min, or until your session ends). If another session holds it: `{error, busy: true, retry_after_s}`, so wait and call again. Calling again from the same session renews the lease |
| `usersim_wait_for_sms_code` | `session_id`, `timeout_s: int = 45` (5–50) | `{found, code}`. Only for the session holding the lease, and only codes from texts that arrived **after** your lease started. Texts on `sms_sender_denylist` are never returned |
| `usersim_solve_captcha` | `session_id` | Observation plus a `captcha` object (detected type, turnstile/audio/challenge results, `note`, `paid` if used) |

Rules:
- **Email only.** Never use Google or GitHub sign-in. Those hosts are blocked in `navigate`/`act`.
- Aliases are always on the dedicated signup inbox `usersim.signups+<tag>@gmail.com`, where `<tag>` is derived from the site host plus a random part. A dot-variant of that inbox is used when you pass `no_plus`. The server refuses to sign up if `GMAIL_USER` isn't the dedicated signup inbox. Never type any other address.
- Mail is read server-side from that Gmail inbox, filtered to this session's alias, site, and mail received since the identity was issued. Mail can take minutes, so call the wait tool again or use the site's "resend" before you give up.
- If verifying lands on a login page, sign in with the **same** email and password. If the app still says "verify your email", reload or sign in again.
- After you submit, wait for the spinner to finish instead of clicking again, because double submits cause errors.
- **CAPTCHAs:** first solve them like a person would (checkbox click, `drag`, `press_and_hold`). Then call `usersim_solve_captcha`. It waits out Cloudflare interstitials, clicks Turnstile, tries the free reCAPTCHA audio route, and waits for Browserbase's built-in solver. On reCAPTCHA v3 pages, a fresh token is minted for free before each click/key. A **paid** solver (CapSolver) only runs when the server sets `MVP_MCP_PAID_CAPTCHA=1`. Its presolve only applies to approved hosts, with at most 2 tries per session, and hCaptcha is never paid for. `usersim_solve_captcha` refuses after **3 calls on the same page**.

### Prompt: `usersim_simulate_user`
Arguments: `session_id`, `persona`, `task`. This returns the instructions for the subagent that plays the user: stay in persona, one action per call, give an honest `thought`, don't guess URLs, follow the signup and captcha rules above, stop when done, stuck, or when a real person would give up, and finish with `usersim_finish`. Step and time limits are filled in from the server config.

## Workflows

### A. One simulated user on one product
1. Get a **public** product URL from the human. Draft a persona and **one** task, then get the human's approval.
2. `usersim_start_session(product_url, persona, task)`. Open `watch_url` for the human.
3. Hand the subagent `session_id`, persona, task and the `usersim_simulate_user` prompt.
4. Loop: read the screenshot and `fields`, then call `usersim_act` with one action and a thought. Use `usersim_observe` if you need a fresh look. Sign up with the signup tools if needed.
5. `usersim_finish(session_id, outcome, notes)`.
6. `usersim_get_report(study_id)` and summarise it. The verdict comes from UserSim's judge, not from the simulated user.

### B. Full e2e study (only study mode)
1. Draft **six** personas, **six** tasks (include signup + verification), and **two** competitor URLs — or leave lists empty for auto-fill. Get approval.
2. `usersim_start_study(product_url, personas, tasks, competitors)` gives you `study_id` and **108** `cells`.
3. For each cell, run one subagent in parallel: `usersim_start_session(study_id=…, cell_id=…)`, then play it with `usersim_act`, then `usersim_finish`. If a start says UserSim is at its limit, wait for running cells to finish.
4. When the last cell finishes, the study report is written automatically. Call `usersim_get_report(study_id)`, and retry in about 30 s if it says the report is still being written.
5. If some cells will never run, call `usersim_finish_study(study_id)`, then `usersim_get_report`.

## Where reports appear
- Report page: `https://usersim.vercel.app/report?study=<study_id>` (`report_url`). Live view: `https://usersim.vercel.app/?study=<study_id>` (`watch_url`). The base URL is `MVP_PUBLIC_BASE_URL`.
- The website reads studies from `gs://usersim-bakeoff-347838016394/mvp_studies/` (the default `MVP_GCS_PREFIX` in `mvp/gcs_store.py`). Since Oct 12 the VM test copy writes there too (start.sh `MVP_GCS_PREFIX=gs://usersim-bakeoff-347838016394`), so a new study opens at `https://usersim.vercel.app/?study=<id>` and `/api/studies/<id>`. Studies from Oct 9–11 were first saved under `mcp-test-vm/` and were copied over on Oct 12.

## Limits

Every cap lives in one file on main: [`mvp/sim_mcp/limits.json`](../../mvp/sim_mcp/limits.json). Each entry has a `value` and an `about` line that explains it.

**How to change a limit (anyone, any agent):**
1. Edit the `value` in `mvp/sim_mcp/limits.json` and open a PR. Run `python -m pytest mvp/test_sim_mcp_limits.py`, which checks that every key is documented and that the defaults in `limits.py` match.
2. Merge it to `main`.
3. Within about 5 minutes (`refresh_s`, plus up to about 5 min of GitHub raw caching), the running server picks it up. It re-reads `https://raw.githubusercontent.com/ShreyasPatel031/UserSim/main/mvp/sim_mcp/limits.json`. **No redeploy and no env vars are needed.**
4. Check what the server is using: `curl -s https://35-202-98-224.sslip.io/api/mcp/limits` shows the effective `values`, the `source` they came from, any `env_overrides`, the last fetch `error` (if any), and today's anonymous spend total.

If the file on main is broken (bad JSON, wrong types), the server keeps the last good values and reports the problem in `error`. A value that is negative or the wrong type is ignored for that key only. Optional per-server override: an env var named `MVP_MCP_<KEY IN UPPER CASE>` (for example `MVP_MCP_ANON_DAILY_USD_PER_IP=1`) beats the file on that one server. Set it only when you must, because it hides later changes to the file. Set `MVP_MCP_LIMITS_URL=off` to stop the server fetching from main (it then uses the bundled copy).

| key | default | meaning |
|---|---|---|
| `allow_anonymous` | `true` | `false` = kill switch. Only callers with a valid bearer token get through; everyone else gets 401 |
| `refresh_s` | 300 | How often the server re-reads the file from main (minimum 30) |
| `max_sessions` | 10 | Browser sessions open at once on the whole server, all callers |
| `max_per_client` | 8 | Open sessions per client IP for callers **with** a token |
| `anon_max_concurrent_sessions_per_ip` | 3 | Open sessions per client IP **without** a token |
| `anon_daily_usd_per_ip` | 6.0 | Estimated $ per client IP per day without a token (day = America/Los_Angeles) |
| `anon_daily_usd_global` | 20.0 | Estimated $ per day for **all** callers without a token, together |
| `est_usd_per_session` | 0.10 | Charged against those budgets when a browser session starts |
| `est_usd_per_step` | 0.01 | Charged per `usersim_act`, `usersim_open_verification_link` and `usersim_solve_captcha` call (a full 40-step session = $0.50) |
| `anon_max_cells_per_study` | 12 | Most runs (persona × task × site) one study may have without a token |
| `anon_allow_sms` | `true` | SMS tools without a token. They're made safe instead of blocked (see the next three rows) |
| `sms_lease_s` | 600 | One session holds the SMS number at a time, for this many seconds or until it closes. Others get `busy` + `retry_after_s`. Applies to every caller |
| `anon_daily_sms_leases_per_ip` | 10 | SMS-number leases per client IP per day without a token |
| `sms_sender_denylist` | apple, icloud, google, g-, banks, … | Texts whose sender or body contains one of these words (whole word, case-insensitive) are **never** returned to any caller: they protect the owner's personal codes (Apple ID, banks, 2FA). Add a word with a PR |
| `anon_allow_paid_captcha` | `false` | Paid captcha solver (CapSolver) without a token |
| `anon_allow_shared_aliases` | `false` | `no_plus` / plain signup addresses without a token. Those can repeat across sessions, so another caller could read the mail. Without a token you only get unique `+tag` aliases |

The $ figures are a **budget estimate**, not metered cost: the server doesn't measure real Browserbase or model spend per call. Change `est_usd_*` when real numbers exist. Anonymous spend is kept per client IP (hashed) and saved to `/var/lib/usersim/mcp_anon_spend.json` (`MVP_MCP_SPEND_FILE`), so a restart doesn't reset it. `usersim_finish` is always allowed, even over budget, so open sessions still get their report.

Fixed limits (code, not the file): 40 steps per session (`MVP_MCP_MAX_STEPS`), 900 s per session (`MVP_MCP_BUDGET_S`), 300 s idle timeout (`MVP_MCP_IDLE_S`), 4 competitors per study, 108 runs per study (`MVP_MCP_MAX_CELLS`), 3 judge votes (`MVP_JUDGE_VOTES`).

When a cap is hit, the tool returns `{"error": "...", "limit": "<key>", "limits_file": "<link>"}`. Concurrent-session errors start with `cap anon_max_concurrent_sessions_per_ip`.

## Costs
- Calling the MCP costs the client nothing beyond its own model tokens. Screenshots are the main token cost.
- The server pays for Browserbase browser time (residential proxies plus built-in captcha solving, `MVP_MCP_BB_PROXIES`) and for judge/report model calls. The paid captcha solver is off by default. When it's on, every token is metered (`cost_usd` in the result) and capped server-side in `mvp/captcha_spend.py`. Paid solving needs `MVP_MCP_PAID_CAPTCHA=1` and a host allowlist; the code has no built-in list. `mvp/captcha_spend.py::paid_hosts()` reads the comma-separated `MVP_CAPTCHA_PAID_HOSTS` env var, plus the study's own sites unless `MVP_CAPTCHA_PAY_STUDY_SITES=0`. The VM test copy runs with `MVP_CAPTCHA_PAY_STUDY_SITES=0` and `MVP_CAPTCHA_PAID_HOSTS=typefully.com,app.upvoty.com,auth.featurebase.app,amplitude.com,app.amplitude.com` (amplitude.com and app.amplitude.com added Oct 12), with a `MVP_CAPTCHA_TOTAL_CAP_USD` cap and a `MVP_CAPTCHA_MIN_BALANCE_USD` floor.
- Every study costs real money and needs the owner's approval.

## Common errors
| error text | meaning / fix |
|---|---|
| `wrong bearer token` (HTTP 401) | Your client sends an old or wrong token. Remove the `Authorization` header: no token is needed |
| `needs a bearer token right now (limits.json allow_anonymous is false)` (HTTP 401) | The open endpoint was switched off in `limits.json` |
| `limit: anon_daily_usd_per_ip` / `anon_daily_usd_global` | Daily budget without a token is used up. It resets at midnight America/Los_Angeles |
| `cap anon_max_concurrent_sessions_per_ip` | 3 sessions are already open from your IP, so finish one first |
| `cap anon_allow_shared_aliases` / `anon_max_cells_per_study` | Not available without a token (see [Limits](#limits)) |
| `the SMS number is busy … Retry in N s` (`busy: true`) | Another simulated user holds the phone number. Wait `retry_after_s` and call `usersim_signup_phone` again |
| `this session no longer holds the SMS number` | Your lease expired or was never granted. Call `usersim_signup_phone` again, then request a new code on the site |
| `limit: anon_daily_sms_leases_per_ip` | 10 SMS leases from your IP today; resets at midnight America/Los_Angeles |
| HTTP 404 on `usersim.vercel.app/mcp` | Wrong path, or the server is on an old build. Check `https://usersim.vercel.app/health` for `engine_version` |
| `product_url must be a public URL …` | localhost, private IP or `.local`: use a public preview/staging URL |
| `UserSim is at its simulated-user limit right now…` | `max_sessions` sessions are already open server-wide, so retry in a few minutes |
| `this client already has the maximum number of open sessions…` | With a token: finish one of your open sessions first (`max_per_client`) |
| `unknown session_id` / `unknown study_id` / `unknown cell_id` | Wrong ID, or the server restarted (sessions live in memory) |
| `cell … was already run` | Each cell runs once |
| `step limit reached` / `time budget used up; call usersim_finish` | Call `usersim_finish` |
| `session is closed (…); call usersim_get_report` | It ended (finished, idle timeout or error) |
| `x,y must be inside the 1280x800 screenshot` | Use screenshot pixel coordinates |
| `Google/GitHub sign-in is not allowed…` | Use the email signup |
| `navigate is limited to the product's own site…` | Click through instead |
| `call usersim_signup_identity and submit the signup form first` | The wait tools need an identity first |
| `only links returned by usersim_wait_for_verification_link can be opened` | Open the exact URL from the wait result |
| `could not open the browser: …` | Browserbase or the first screenshot failed. Retry once |
| `at most 4 competitors`, `… over the 60-run limit` | Shrink the study |

## Troubleshooting
- **401:** your client sends a wrong token, so remove the header. If there's no header and you still get 401, `allow_anonymous` is off in `limits.json`.
- **Caps look wrong:** `curl -s https://35-202-98-224.sslip.io/api/mcp/limits` shows the values in force and where they came from.
- **Clicks land in the wrong place:** coordinates must come from the 1280×800 screenshot you were given. Prefer the exact x,y in `fields`.
- **Form "does nothing" on submit:** read `unfilled_fields`, `page_errors` and `captcha.hint`. Usually there's an empty required field or a captcha with no token.
- **No verification mail:** confirm that the form really submitted, call the wait tool again (up to 240 s per call), or click "resend". If the site rejected `+`, call `usersim_signup_identity(no_plus=true)` and retype the email.
- **Report link 404 on the site for test-server studies:** see the `mcp-test-vm/` note above.
- **Long calls time out through a proxy:** `start_session` takes about 5–20 s and the wait tools up to 240 s, so raise your client's HTTP timeout.
