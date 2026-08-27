# Full270 audit — why ~13% SUCCESS (not “all blocked”)

**Manifest:** `results/capability/product_full270_browser_use_full270_flashlite_m40.json`  
**n = 270** · model `gemini-2.5-flash-lite` · `max_actions=40`

## Headline correction

| Label in summary | Count | % of 270 | What it actually is |
|------------------|------:|--------:|---------------------|
| SUCCESS | 25 | **9.3%** | Judge agreed journey done |
| **BLOCKED** (status) | **79** | **29%** | Auth walls, empty/WAF loads, etc. — **not** the other 87% |
| FAILURE | 166 | **61%** | Premature done, harness timeouts, planning |

**Where “13%” comes from:** the manifest reports `success_rate_scored = 25/191 = 13.1%`. That denominator is **270 − 79 BLOCKED** (eligible = non-BLOCKED). It does **not** mean the other 87% of the run were blocked. Of all 270:

- ~9% SUCCESS
- ~29% BLOCKED
- ~61% FAILURE (mostly premature-done + wall-clock timeouts)

So: **only ~29% are BLOCKED**, not “the rest.”

## Root-cause buckets (re-labeled)

| Bucket | n | % | Meaning |
|--------|--:|--:|---------|
| PREMATURE_DONE_FAIL_JUDGE | 71 | 26% | Agent called `done` / stopped; judge said journey incomplete |
| TIMEOUT_HARNESS | 67 | 25% | Hit **task wall 1720s** (`40×40+120`); 0 actions recorded in timeout path |
| PAGE_LOAD_WAF | 36 | 13% | Empty DOM / Cloudflare / black screen / unresponsive SPA |
| AUTH_LOGIN_WALL | 36 | 13% | Login / Google SSO / Vapi SSO |
| SUCCESS | 25 | 9% | |
| NO_BASELINE_AGENT | 15 | 6% | Journeys 2–5 require an existing agent; account empty |
| PLANNING_STEP_CAP | 13 | 5% | Burned step budget without finishing |
| BLOCKED_OTHER | 7 | 3% | Other blocked |

## By platform

| Platform | SUCCESS | Worst modes |
|----------|--------:|-------------|
| Retell | **13/90** | Premature judge fails; some auth |
| Bland | **9/90** | Premature + timeouts; some Google login redirects |
| Vapi | **3/90** | **Page-load/WAF + timeouts dominate**; SSO/login |

Vapi final URLs for many “BLOCKED” runs are still `https://dashboard.vapi.ai/` with judge text about **empty DOM / failed to load / Cloudflare** — not always a clean login URL.

## By journey

Harder journeys (integration / routing / test) succeed less. Rapid setup has the most SUCCESSes (10).  
**67 TIMEOUT runs lost `goal_key`/`persona_id` in the timeout result object** (bug in timeout path metadata) — they still count as 67 cells of the 270.

## What actually went wrong

### 1. Auth / session fragility (~13% clear login + part of Vapi blanks)
- Sessions were packed once and shipped to **36 GCP Spot VMs**.
- **Vapi WorkOS / ORG JWTs in localStorage are ~1h TTL.** Fleet launched ~07:26Z; Vapi token `exp` ~08:07Z while shards were still running → mid-fleet Vapi auth rot.
- Some Bland/Retell runs redirected to Google / Auth0 login (cookies not enough from datacenter IP, or session partial).
- Runner passes **raw session file path** into Browser Use (`storage_state=str(path)`), not always the sanitized dict (origins missing `localStorage` key on some entries).

### 2. Harness timeouts (~25%)
- Wall clock = `max_actions * 40 + 120` = **1720s (~28 min)** per hung task.
- All 67 HARNESS failures are `task_wall_timeout:1720s` with `num_actions=0` — browser/agent never completed a recorded step (stuck on load or hung Chromium).
- Correlates with Vapi blank loads and overloaded Spot VMs (8 parallel Chromium per box).

### 3. Premature “done” / harsh journey grading (~26%)
- Agents often reached a related page (dashboard, knowledge, agent list) and stopped.
- Judge required fuller journey success (webhook configured, routing built, simulator+analytics, etc.).
- flash-lite + complex product UIs → shallow completions.

### 4. Experiment design interaction (~6%)
- Journeys 2–5 require an **existing baseline agent**. When the account had none (or create from journey 1 failed), agents correctly stopped — counted as failure vs SUCCESS.

### 5. Not primarily “site blocked like Mind2Web WAF”
- Unlike Mind2Web full100 Akamai blocks, these are **product-console auth + SPA load + agent quality** issues under fleet concurrency.

## Evidence samples
- Bland BLOCKED → `accounts.google.com/...` OAuth or `app.bland.ai/login`
- Vapi BLOCKED → `dashboard.vapi.ai/` with empty DOM / Cloudflare in judge text; some `/login` / `/sso`
- Retell better when session held; failures more “didn’t finish journey”

## Recommended fixes before re-run
1. **Refresh sessions immediately before fleet**; for Vapi, refresh tokens every ~45m or inject cookie-only auth that lasts the wave.
2. Pass **sanitized `storage_state` dict** (not raw path) into Browser Use; rewrite session files on pack.
3. Cut concurrency (e.g. **4 workers/VM** or more VMs) so SPAs actually load.
4. Fix timeout result to copy `persona_id` / `goal_key` / `seed`.
5. Pre-seed one baseline agent per platform before journeys 2–5 (or run journey 1 as setup, not scored the same way).
6. Consider `gemini-2.5-flash` (not lite) for product UX journeys; keep lite only for smoke.
7. Use the **~30 reserve** to re-run AUTH + TIMEOUT cells with fixed auth — do not expand casually into new cells.

## Bottom line
Fleet mechanics worked (**36/36 shards, 270 runs, ~$5**). Outcome quality did **not**: auth TTL + Vapi load failures + timeouts + premature done against hard journeys crushed SUCCESS to ~9–13%. This is **not** “87% site-blocked.”

---

## Re-run (in flight): `full270_flash_m40`

| Change | Detail |
|--------|--------|
| Model | `gemini-2.5-flash` (~$19 API est. same tokens) |
| Concurrency | **WORKERS=4** (was 8) |
| Auth | Sanitized `storage_state` dict; Vapi WorkOS refresh via `workos_rt` before pack/relaunch |
| Metadata | Timeout stubs keep persona/goal/seed |
| Verify | bland/vapi/retell **logged_in** after refresh (2026-08-27) |
| Fleet | 36 Spot VMs launched; watcher relaunches preempted shards |