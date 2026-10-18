# UserSim handover (from Grok Bot, Oct 18 2026)

**No one needs Grok Bot's approval for anything here.** Grok Bot is no longer admin. Everything below can be changed by anyone with repo access (PRs to `main`) or GCP access (`<redacted>`).

This file holds **no secret values**. It says where each secret lives and how to rotate it.

The facts here were checked on Oct 18 2026, around 11:20 AM PT, against the live server, the repo, GCP (read-only) and the shared box. Anything not checked is marked *unverified*.

---

## 1. Production MCP server

- **URL:** `https://35-202-98-224.sslip.io/mcp`. Anyone can call it, with **no token**.
- **17 tools** were checked live with no token:
  - Studies and sessions: `usersim_start_study`, `usersim_finish_study`, `usersim_start_session`, `usersim_observe`, `usersim_act`, `usersim_finish`, `usersim_get_report`
  - Agent mode: `usersim_predict_experience`
  - Human-run planning: `usersim_plan_human_run`, `usersim_combine_human_run`
  - Signup and verification: `usersim_signup_identity`, `usersim_wait_for_verification_code`, `usersim_wait_for_verification_link`, `usersim_open_verification_link`, `usersim_signup_phone`, `usersim_wait_for_sms_code`, `usersim_solve_captcha`
- **Agent mode:** `mvp/agent_mode.py`. It predicts a user's experience from scraped reviews and needs `APIFY_TOKEN`, which is **missing right now** (see §3).
- **Human mode:** `mvp/human_mode.py`. A real cloud browser (Browserbase) driven by the caller's own model, through the tools above.
- **Health:** `GET /health` returns the deployed `engine_version`. `GET /static/build.txt` returns the deployed SHA and time.
- **VM:** `usersim-grokbot-web`, zone `<redacted>-a`, project `<redacted>`, e2-standard-4. Its service account is the default compute SA, `347838016394-compute@developer.gserviceaccount.com`.

### Deploy = merge to main
- The systemd timer `usersim-pull-deploy.timer` runs `/opt/usersim/bin/vm_pull_deploy.sh` (source: `mvp/deploy/vm_pull_deploy.sh`) **every 3 minutes**.
- When GitHub `main`'s SHA differs from `/var/lib/usersim/deployed_sha`, it:
  1. waits up to **600 s** for running studies to drain (it deploys anyway after that);
  2. downloads the public tarball into `/opt/usersim/app`;
  3. runs pip install;
  4. sets `USERSIM_ENGINE_VERSION` in `/etc/usersim/env`;
  5. restarts `usersim.service`.
- **Observed Oct 18, ~11:21 AM PT:** `main` was `76efa976` but the deployed version was still `3017e26d`. The timer was waiting on 7–23 running studies from other callers. With the server busy, a deploy can lag by about 10+ minutes per attempt. Check `/static/build.txt`.
- `mvp/deploy/bootstrap_vm.sh` does the one-time setup: it installs the timer and copies `/etc/usersim/env` secrets into Secret Manager. It's already done on this VM. Re-run it only on a new host: `sudo bash mvp/deploy/bootstrap_vm.sh`.
- **Old GCS watcher:** `/opt/usersim/watch.sh` is **still running** on the VM (pid 3084 on Oct 18). It is the legacy deploy path, which uploads a code tarball to GCS. Pull-deploy replaced it. It's harmless but redundant, and anyone may disable it.

### SSH, restart, logs
```bash
source /workspace/gcp-auth.sh        # on the shared box; elsewhere use any GCP identity with IAP + compute access
gcloud compute ssh usersim-grokbot-web --zone <redacted>-a --project <redacted> --tunnel-through-iap
sudo systemctl restart usersim.service
sudo journalctl -u usersim.service -n 200 --no-pager            # app logs
sudo journalctl -u usersim-pull-deploy.service -n 50 --no-pager # deploy logs
systemctl list-timers usersim-pull-deploy.timer
cat /var/lib/usersim/deployed_sha
```
- **Roll back:** revert the commit on `main` and merge. The timer redeploys it.

## 2. Settings: `mvp/sim_mcp/limits.json`

- There are 28 settings. Only `value` is read; `about` explains each one.
- The server re-reads the file from **public GitHub `main`** every `refresh_s` = 300 s (**~5 min**). No redeploy is needed.
- To see live values, their source, today's spend, and which secrets are present (never their values):
  `curl -s https://35-202-98-224.sslip.io/api/mcp/limits`
- **Current values are unrestricted, per Shreyas (PR #108, `c0aaffe4`).** Verified live:
  - `allow_anonymous`: true
  - Concurrent sessions: 60 total, 60 per client, 60 per anonymous IP
  - `max_steps`: 200; `budget_s`: 1800; `max_cells`: 108
  - `anon_daily_usd_per_ip` and `anon_daily_usd_global`: 10000 (effectively no cap)
  - `paid_captcha` and `anon_allow_paid_captcha`: true
  - `anon_allow_shared_aliases`: true
  - `anon_allow_sms`: true, with `sms_lease_s` 600
  - The `sms_sender_denylist` stays on. It keeps the owner's Apple, bank and 2FA texts away from all callers.
- **Change a setting:** edit `value`, open a PR and merge it. **No approval is needed.** An optional per-host override is the env var `MVP_MCP_<KEY>` (none are set). For the full reference, see `docs/mcp/CONFIG.md`.
- Shreyas asked that no one add caps without asking him first.

## 3. Secrets

- **Where:** GCP Secret Manager, named `usersim-<ENV_VAR>` in `<redacted>`. If a secret is missing there, the server falls back to `/etc/usersim/env` on the VM. Loader: `mvp/secrets_store.py`, re-read every ~5 minutes.
- **Access:** the VM's service account can read `usersim-*` secrets.

**In Secret Manager** (created Oct 18 around 8:22 AM PT; the live server reports `source: secret_manager`):
- `GMAIL_APP_PASSWORD`
- `BROWSERBASE_API_KEY`
- `CAPSOLVER_API_KEY`
- `MVP_SMS_PHONE`
- `MVP_NTFY_SMS_TOPIC`

There's also an older, unused secret, `usersim-grokbot-browserbase-key`, from Sep 26.

**Still env-only in `/etc/usersim/env` on the VM:**
- `MVP_MCP_TOKEN_FILE` points at the operator bearer-token file. That token skips the anonymous caps, which are off now anyway.
- The rest of that file is non-secret config: `GMAIL_USER`, `BROWSERBASE_PROJECT_ID`, `MVP_*`, and so on.

**Missing everywhere** (the server reports them as `missing`):
- `APIFY_TOKEN`: **agent mode can't scrape reviews until it's added.** The Apify account was reported as having a **$105/month cap with about $20–25 left** on Oct 18 (*unverified*; check the Apify billing page).
- `MVP_CAPTCHA_API_KEY`: CapSolver goes through `CAPSOLVER_API_KEY` instead.
- `MVP_OWNER_PHONE`, `MVP_NTFY_TOKEN`, `MVP_SMS_API_KEY`, `MVP_TEXTVERIFIED_API_KEY`, `MVP_MCP_TOKEN`: all optional.

**Add or rotate a secret** (the value is read from stdin, so it never appears in shell history or output):
```bash
gcloud config set project <redacted>
gcloud secrets create usersim-APIFY_TOKEN --replication-policy=automatic      # first time only
printf '%s' "$APIFY_TOKEN" | gcloud secrets versions add usersim-APIFY_TOKEN --data-file=-
# confirm (presence only): curl -s https://35-202-98-224.sslip.io/api/mcp/limits | jq '.secrets.secrets.APIFY_TOKEN'
```
- If a new secret's name isn't covered by an existing `usersim-*` IAM grant, give the VM service account `roles/secretmanager.secretAccessor` on it.
- **On the shared box,** secret files are listed by name in `/workspace/secrets/README.md`. Never print them.
  - GCP service-account key: `/workspace/secrets/usersim-cloud-agent-sa.json`, used by `gcp-auth.sh`
  - GitHub token: `/workspace/.github-token.env`
  - Box secret store: `/home/box/agent-data/box-secrets.json` (Browserbase, CapSolver, Gmail app password, `VERCEL_TOKEN`)
  - Operator MCP token: `/workspace/secrets/usersim_mcp_token.env`

## 4. Website (Vercel)

- **Domains:** `atelier-sim.com`, `www.atelier-sim.com` and `usersim.vercel.app`. They're all Vercel project **`usersim`**, team **`shreyaspatel031s-projects`**.
- **Every push to `main` auto-deploys production.**
- **Hobby plan limits:** 100 deployments per day, and builds get rate-limited. On Oct 18 the limit was hit, so new builds were turned away.
- **Oct 18 manual alias:** `atelier-sim.com` and `www` were pointed by hand at deployment `dpl_EJTBsG2ZaJi2paZbuzuidFdWGvkj`, built from branch `fix/atelier-landing`. The next successful `main` deploy re-aliases the domain back to `main`. That's fine, because `main` has the landing page (PR #106, `1499b7de`).
- **Landing page:** `mvp/static/landing.html` at `/`. The app is at **`/app`**. Verified live: `/` has title "Atelier", and `/app` returns 200.
- **`/mcp` rewrite:** commits `52489f7d` and `9ef2873c` forward `atelier-sim.com/mcp` to the VM. They're on branches `fix/atelier-landing` and `atelier-landing-mcp-rewrite` only, **not on `main`**.
  - Right now `atelier-sim.com/mcp` answers (406 to a plain GET, which is MCP's normal reply) only because the manual alias above includes the rewrite.
  - **The next `main` deploy will drop `/mcp`** unless the rewrite is merged to `main` first. Use `https://35-202-98-224.sslip.io/mcp` as the canonical URL.
- **Vercel token:** `VERCEL_TOKEN` in `/home/box/agent-data/box-secrets.json`. An older, limited-scope token is in `/workspace/.vercel-token.env.old-limited`; prefer the box-store one. Either token is bound by the Hobby plan's deploy and build limits. `/workspace/.vercel-token.env`, which `secrets/README.md` mentions, no longer exists.

## 5. Getting code onto `main`

- **If you have GitHub access:** open a normal PR and merge it. A merge to `main` deploys both the MCP VM (§1) and Vercel (§4).
- **From the shared box, which can't push to GitHub:** use the bundle plus cloud-agent route.
  1. Commit on a local branch.
  2. `git bundle create x.bundle origin/main..<branch>`
  3. Upload it to `<redacted>/handoff/` and make a signed URL (`gcloud storage sign-url`, ~6 h).
  4. Launch a Cursor cloud agent on `ShreyasPatel031/UserSim`. Its job: download the bundle, check the sha256, `git bundle verify`, fetch the branch, push normally (never `--force`), open the PR and merge it with a merge commit.
  - Example prompt: `/workspace/e2e18/out/cloud_agent_prompt.txt`.
  - Use composer-2.5 cloud agents. The "Other models" pool is at 100% until Oct 26.

## 6. Signups, inboxes, phone

- **Test accounts:** fresh `usersim.signups+<tag>@gmail.com` aliases, read over IMAP with `GMAIL_APP_PASSWORD`. The MCP hands them out through `usersim_signup_identity` and the verification-wait tools.
  - Sign up only on products UserSim has never signed up on before.
  - **No Google or GitHub sign-in.**
- **SMS:** the real phone number (`MVP_SMS_PHONE`) forwards texts to an ntfy topic (`MVP_NTFY_SMS_TOPIC`). The MCP serves codes through `usersim_signup_phone` and `usersim_wait_for_sms_code`.
  - One session holds the number at a time (600 s lease).
  - A session only sees texts that arrive after its lease starts.
  - The denylist hides personal senders.
- **`<redacted>`:** **never use it for anything**, except as Shreyas's Apple ID for iOS testing on BrowserStack.
- **`<redacted>`:** only for GCP and his day job.
- Never sign in to Google in the box browser. Never add a card or a paid solver without Shreyas's OK. Never contact founders. Never send external messages unasked.

## 7. Definitions and docs (on `main`)

- `docs/E2E_TEST.md`: **the only definition of an e2e test.** That's the full study: target plus 2 competitors, 6 personas, 6 tasks, 108 cells, with signup included. Reduced runs are not e2e tests, and the API rejects them.
- `docs/mcp/README.md`: client guide.
- `docs/mcp/CONFIG.md`: every `limits.json` setting.
- `docs/mcp/OPERATIONS.md`: deploy, secrets, rollback.
- Other handoffs on `main`: `AGENTS.md`, `CLOUD.md`, and the latest handoff commit `76efa976`.

## 8. Spend tracking

- **Meter:** `/workspace/spend-meter`. Run it with `export PATH=/home/box/google-cloud-sdk/bin:$PATH && python3 /workspace/spend-meter/meter.py`. It reads GCP compute plus Vertex token use from Cloud Monitoring.
  - Outputs: `latest.json`, `history.jsonl`, `spend_watch_history.jsonl`
  - Planned load: `planned.json`
- **Targets:** about **$50 a day** total. R&D split: $25 Training Lead, $25 Social Sim, $50 product. Studies need Shreyas's approval for spend.
- **Oct 18 snapshot (10:41 AM PT):**
  - Vertex today was $71.78: `<redacted>` $62.92, `claude-haiku-4-5` $6.86 (from the stopped human-mode runs), `flash-lite` $2.00.
  - The GCP 24-hour projection was about $122.
  - The MCP server's own estimate of today's anonymous use was $9.82, across 46 IPs.
- **Vertex API key (id redacted):** the likely source of the overnight Gemini Flash burst (about $70). **Whether to disable it is undecided; it's Shreyas's call.**
- **Idle disks:** about $27/day; deleting them is pending his decision.

## 9. Open work and loose ends

- **5 human-mode e2e studies, stopped for cost** at $5.96 spent (driver: `claude-haiku-4-5`, about $0.018/step):

  | Study | Product | Competitors | Token |
  |---|---|---|---|
  | `030c4d5e` | workflowy.com | checkvist, amplenote | no token |
  | `6242eaa7` | nuclino | slite, tettra | operator token |
  | `85ddea1a` | parabol.co | easyretro, teamretro | operator token |
  | `292ea2d7` | meistertask | taiga, zenkit | operator token |
  | `0dec10cf` | mindmeister | mindomo, gitmind | operator token |

  - Reports: `https://atelier-sim.com/report?study=<full id>`. Full IDs are in `/workspace/e2e18/hum/`.
  - Runner: `/workspace/e2e18/hrun.py`. The repo version is `scripts/mcp_study_runner.py` on `main`; PR #104 added the signup and verification tools.
  - Cost options given to Shreyas for all 5: Gemini 2.5 Flash driver ~$50–65, Haiku with caching ~$110–130, Flash-Lite ~$20–30 (weaker at signups). **No choice made yet.**
- **Planner bugs:** the server planner leaves out a signup task and creates tasks that don't fit the product. This needs a fix before the human-mode e2e results can be trusted.
- **Agent mode** still needs testing on 10–20 new YC startups. It's blocked on `APIFY_TOKEN` (§3).
- **Unmerged branches** (commits ahead of `main`):
  - `mcp-existing-email-anon-owner` (1): sign back in with an earlier alias; session-id ownership for rotating IPs
  - `claude/focused-mayer-6cxxnk` (1): one test account per study and site, with a daily signup cap
  - `claude/hopeful-edison-ir9kw8` (1): resume studies after a restart; check rivals do the same job
  - `claude/great-dijkstra-hy0gnm` (26): Android phone study on a Mac emulator
  - `claude/upbeat-hopper-u9kqgk` (5): WellSky sandbox gateway tests
  - `fix/atelier-landing` (3): includes the Vercel `/mcp` rewrite
  - **PR #67** (open, by Devin): Apple ID sign-in with SMS 2FA, plus an Android app agent
- **Pending Shreyas decisions:**
  - idle disks
  - GitGuardian incident 37980789
  - the Reframe card
  - the Vercel `/mcp` rewrite
  - Vertex API key (id redacted)
  - Social Sim's proposal
  - Outreach's top five (on hold)
- **Teammate agents** (Grok Bot agents on the shared box):
  - **Product Agent:** UserSim product work; `main` is final; production MCP and website
  - **Training Lead:** social-simulation fine-tuning program (its latest DPO result was a FAIL)
  - **Social Sim Research:** research only (benchmarks and papers)
  - **Outreach:** outreach leads. Leads are excluded from testing.
  - Shreyas also runs a separate agent that drives the human-mode MCP. On Oct 18 it was running many studies, which is why deploys waited.

## 10. Grok Bot routines that may still run (monitoring only)

- **Spend watch, every 3 h:** runs the spend meter, reads the Cursor usage page, and alerts if the GCP projection or Cursor pool use jumps. It writes `/workspace/spend-meter/spend_watch_*.json*`.
- **Daily spend check:** a once-a-day summary of GCP and Vertex spend against the $50 target.
- **Morning sweep:** a morning summary of overnight agent, PR and spend state (`/workspace/morning_summary.md`).

They change nothing. **Anyone can ignore, replace or delete them.** The schedule lives in Grok Bot's automation settings, not in the repo.
