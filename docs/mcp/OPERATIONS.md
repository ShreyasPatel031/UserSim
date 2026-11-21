# UserSim MCP operations (deploy, settings, secrets)

Anyone with **repo access** or **GCP access** to project `project-amer-scs-sandbox` can operate the public MCP server. **No approval from Grok Bot or the founder is required.**

| What | How | Typical time |
|------|-----|----------------|
| Deploy server **code** | Merge to `main` | VM pull timer ~3 min (+ up to 10 min if studies are running) |
| Change **settings** (caps, `max_steps`, feature flags) | PR → merge `mvp/sim_mcp/limits.json` | Hot-reload ~5 min |
| Add / rotate **secrets** | `gcloud secrets versions add` (below) | Hot-reload ~5 min |
| Roll back code | Revert commit on `main` and merge | Same as deploy |
| Roll back a setting | Revert `limits.json` on `main` | ~5 min |

## Deploy (merge to main)

Production VM `usersim-grokbot-web` runs **`usersim-pull-deploy.timer`**: every **~3 minutes** it compares GitHub `main`’s SHA to `/var/lib/usersim/deployed_sha`. When `main` moves, it:

1. Waits until **no studies / Browserbase sessions** are running (polls `/api/runtime/status`, up to **~10 minutes**).
2. Downloads the public tarball from GitHub (`codeload.github.com/.../tar.gz/main`).
3. Syncs into `/opt/usersim/app`, updates `mvp/static/build.txt`, `pip install`s if needed, and **`systemctl restart usersim`**.

**Merging to `main` is deploying.** No GitHub Actions secrets and no manual `gcloud` upload are required on the happy path.

Scripts in repo:

- `mvp/deploy/vm_pull_deploy.sh` — deploy logic
- `mvp/deploy/usersim-pull-deploy.service` + `.timer` — systemd units
- `mvp/deploy/bootstrap_vm.sh` — one-time install (see below)

### One-time VM bootstrap

On the VM (sudo + `gcloud` auth to `project-amer-scs-sandbox`):

```bash
sudo bash mvp/deploy/bootstrap_vm.sh
```

Or from `main` without a checkout:

```bash
curl -fsSL https://raw.githubusercontent.com/ShreyasPatel031/UserSim/main/mvp/deploy/bootstrap_vm.sh | sudo bash
```

This installs `/opt/usersim/bin/vm_pull_deploy.sh`, enables the timer, and **migrates** secret values from `/etc/usersim/env` into Secret Manager (`usersim-<VAR>`).

## Browsers: seed VMs (`browser_backend = seed_vm`)

Since Nov 17 the engine's browsers run on our own GCP signup seeds, not Browserbase (`browser_backend` in
`limits.json`; `browserbase` is kept only as a fallback path).

- **Seeds:** `usersim-signup-seed-N` (us-central1-a, e2-standard-8 (seed 0: e2-standard-2 until resized), standard provisioning, VPC `usersim-seed-network`,
  static egress IP on the NIC, durable identity disk). Create / start: `scripts/vm/create_signup_seed.sh`
  (`SEED_INDEX=N`, `SKIP_PROVISION=1` to only start). ~$0.27/h per seed running (+ ~$0.005/h per static IP).
- **Seed Chromium:** `usersim-seed-cdp.service` (headed under Xvfb, CDP bound to the seed's **127.0.0.1:9222** only).
  Install: `gcloud compute ssh usersim-signup-seed-N --zone=us-central1-a --tunnel-through-iap --command='bash ~/usersim/scripts/vm/install_seed_cdp.sh'`.
  Each simulated user is one isolated browser context; `producthunt.com`, the metadata server and private IPs are
  blocked inside every context.
- **Reaching CDP:** on `usersim-grokbot-web`, `usersim-seed-tunnel@N.service` holds an IAP SSH tunnel
  (`-L 127.0.0.1:1922N:127.0.0.1:9222`). Install: `sudo SEEDS="0 1" bash mvp/deploy/install_seed_tunnels.sh`.
  The VM's service account needs `roles/iap.tunnelResourceAccessor` and SSH to the seeds. No firewall rule opens
  9222: the seed VPC only admits `35.235.240.0/20 -> tcp:22` (IAP).
- **Camoufox** (`browser_engine`, default `camoufox`; Shreyas, Nov 17: "always run camoufox"): every seed also runs
  `usersim-seed-camoufox.service` (`scripts/vm/seed_camoufox_server.py`), a Camoufox (Firefox) Playwright server on
  the seed's **127.0.0.1:9333** (path `/usersim`), with one fingerprint preset chosen once and kept on the identity
  disk (`camoufox_preset.json`); nothing is randomized per run. The tunnel forwards it to the MCP host's 1932N. The
  engine connects with `playwright.firefox.connect`; client and server Playwright must be the same version
  (requirements.txt pin, also pinned by `seed_provision.sh` / `install_seed_camoufox.sh`). Install / restart on a seed:
  `bash ~/usersim/scripts/vm/install_seed_camoufox.sh` (also run by `install_seed_cdp.sh`). Roll back: set
  `browser_engine` to `chromium` in limits.json (both services stay up). Lost on Camoufox (Chromium-only CDP):
  the device-metrics viewport fallback and the raw `Page.captureScreenshot` fallback for pages whose screenshot stalls
  on web fonts (a second Playwright screenshot without animations is tried instead); the probe's wedge and
  extension-service-worker checks are CDP checks and do not apply.
- **Seed hardening** (all in `install_seed_cdp.sh`, also run at the end of `seed_provision.sh`):
  - AppArmor profile `usersim-seed-chrome` grants `userns` to Playwright's Chromium (Ubuntu 24.04 otherwise kills it
    with "No usable sandbox"); the sandbox stays on.
  - sshd `ClientAliveInterval 15` / `ClientAliveCountMax 2`: a dropped IAP tunnel leaves no half-open CDP client.
    Such a client holds auto-attach with `waitForDebuggerOnStart`, and then every new page on the seed hangs.
  - `usersim-seed-cdp-watchdog.timer` (root, every minute) runs `mvp/sim_mcp/seed_probe.py` locally: fresh context,
    `data:` URL load, JS eval, 5 s. Two failures in a row restart `usersim-seed-cdp`.
- **Engine health:** before handing out a slot the engine runs the same deep probe through the tunnel (cached 20 s;
  re-probed at once after a failed open), so users are never sent into a wedged browser.
- **Dropped connection mid-session:** Chromium disposes a context when the CDP connection that made it drops, so the
  page cannot be reattached. The engine saves cookies + localStorage + URL after every step and, on the next tool
  call, reconnects to the same seed, rebuilds the context from that state and reloads the URL (up to 3 times per
  session; the step says so, and unsaved form input is lost).
- **Saved accounts** (`seed_saved_accounts`, `mvp/sim_mcp/site_states.py`): seeds are datacenter IPs without
  Browserbase's residential egress or captcha solver, so signup walls stop many cells. A cell whose task is not itself
  a signup starts signed in from `gs://usersim-bakeoff-347838016394/seed_states/<domain>.json`, on the seed that saved
  it when free; the start_session reply carries `signed_in`. A cell that ends on a signed-in page (judge) or with a
  verified signup writes its state back. Fill the bucket from a seed's identity disk (site_states/ + profiles/):
  `gcloud compute ssh ubuntu@usersim-signup-seed-N --zone=us-central1-a --tunnel-through-iap --command='~/usersim/.venv/bin/python ~/usersim/scripts/vm/export_seed_states.py --upload'`
  (dry run without `--upload`; `--force` overwrites domains already in the bucket).
  A signed-in cell opens the app URL the state implies (`app.<domain>` or a workspace subdomain), not the marketing
  homepage, and the simulate-user prompt and every observation say it is already signed in. If that page is a
  login/signup page the state is dead: it is flagged `dead` in the bucket, its cookies are cleared and the cell starts
  normally. Which states still sign in (run on a seed, same egress IP):
  `~/usersim/.venv/bin/python ~/usersim/scripts/check_saved_states.py [--only a.com,b.com] [--mark-dead]`. These are shared test accounts:
  anyone running a study on that site acts inside them.
- **Capacity:** each seed carries `seed_sessions_per_seed` users, or N for an endpoint written `url#N` (seed 0 is
  e2-standard-2: `#3`). Callers past that wait `seed_wait_s`, then get "busy, retry in ~30 s" and the cell stays
  queued (not counted as a start failure).
- **Check:** `curl -s https://35-202-98-224.sslip.io/api/mcp/limits | jq .browsers` → backend + each seed's
  `healthy` / `in_use`.
- **Add a seed:** create it, install its CDP service, add its tunnel (`SEEDS="… N"`), then add
  `http://127.0.0.1:1922N` to `seed_cdp_endpoints` by PR.

## Settings (`limits.json`)

All non-secret runtime knobs live in **[`mvp/sim_mcp/limits.json`](../../mvp/sim_mcp/limits.json)**. See **[CONFIG.md](CONFIG.md)** for the full list.

1. Edit `value` (and `about` if you change behavior/cost).
2. Open a PR, merge to `main`.
3. Confirm: `curl -s https://35-202-98-224.sslip.io/api/mcp/limits | jq .values,.value_sources`

Optional per-host override: `MVP_MCP_<KEY>` env (avoid unless debugging).

## Secrets (GCP Secret Manager)

**Never** put secrets in `limits.json` or git. The server loads them at startup and **re-reads every ~5 minutes** (`mvp/secrets_store.py`), with fallback to **`/etc/usersim/env`**.

- **Project:** `project-amer-scs-sandbox` (override: `USERSIM_GCP_PROJECT`)
- **Name:** `usersim-<ENV_VAR>` (exact env var name)

### Rotate or add a secret

```bash
gcloud config set project project-amer-scs-sandbox
printf '%s' 'NEW_VALUE_HERE' | gcloud secrets versions add usersim-MVP_CAPTCHA_API_KEY --data-file=-
```

Create the secret the first time:

```bash
gcloud secrets create usersim-MVP_CAPTCHA_API_KEY --replication-policy=automatic
```

The VM service account needs **Secret Manager Secret Accessor** on these secrets.

### Secret names and purpose

| Secret (`usersim-…`) | Purpose |
|----------------------|---------|
| `GMAIL_APP_PASSWORD` | IMAP app password for the dedicated signup Gmail inbox |
| `BROWSERBASE_API_KEY` | Browserbase API key (MCP + website browsers) |
| `MVP_CAPTCHA_API_KEY` | CapSolver / paid captcha API key |
| `CAPSOLVER_API_KEY` | Alias used by some code paths for the same key |
| `APIFY_TOKEN` | Apify token for `usersim_predict_experience` scrapes |
| `MVP_SMS_PHONE` | Owner phone (E.164) used for SMS verification |
| `MVP_OWNER_PHONE` | Optional owner phone metadata |
| `MVP_NTFY_SMS_TOPIC` | ntfy topic where the phone forwards SMS (sensitive) |
| `MVP_NTFY_TOKEN` | Bearer token for private ntfy |
| `MVP_SMS_API_KEY` | TextVerified (or other) SMS API key |
| `MVP_MCP_TOKEN` | Optional bearer token(s) that skip anonymous caps |
| `MVP_TEXTVERIFIED_API_KEY` | Legacy TextVerified key name |

Non-secret config (URLs, project ids, feature toggles that are not credentials) may remain in `/etc/usersim/env` or move to `limits.json` when appropriate.

## Website /ph and /try (Vercel env)

- `PH_CLIENT_ID`, `PH_CLIENT_SECRET`: the site's own Product Hunt app (not the pipeline's), for the live board.
- `CRON_SECRET`: Bearer secret for `/api/ph/cron/snapshot` (15-minute record).
- `TRY_SIGNING_KEY`: signs /try run tokens.
- New env values take effect only on the next deployment. Deploys started through Vercel's API have their own daily cap
  (`api-deployments-free-per-day`); a merge to main deploys through git.
- Health: `/api/ph/health` → `live_board.configured` should be true and `age_s` under about 120.

## Check what is live

```bash
curl -s https://35-202-98-224.sslip.io/health
curl -s https://35-202-98-224.sslip.io/static/build.txt
curl -s https://35-202-98-224.sslip.io/api/mcp/limits | jq .
```

- **`/health`** — `engine_version` (from `mvp/static/build.txt` or git), `content_id`, `config_hash`
- **`/static/build.txt`** — deployed short SHA, UTC timestamp, branch
- **`/api/mcp/limits`** — every `limits.json` value, **`value_sources`** per key (`env`, GitHub URL, `bundled`, `default`), and **`secrets`** with `present` + `source` only (**never** secret values)

## Roll back

- **Code:** `git revert` the bad commit on `main`, merge — pull-deploy installs the previous tree.
- **Settings:** revert the `limits.json` PR on `main`.
- **Secrets:** add a new Secret Manager **version** with the old value (`gcloud secrets versions add …`); previous versions remain in GSM history.

## Who may do this

Any collaborator on **ShreyasPatel031/UserSim** or anyone with **GCP Secret Manager + VM SSH** access to `project-amer-scs-sandbox` / `usersim-grokbot-web`. No single “bot operator” gate.


## CAPTCHA visibility (Oct 23)

Every paid CAPTCHA attempt is stored per session as `captcha_paid_log` (in the study JSON under `live_sessions`, and
as `action_args.paid` on the trace step): the ledger rows it produced (`createTask` solved/cost, or `skip` with the
reason: `host_not_paid`, `solve_attempt_cap`, `per_site_cap`, `total_cap`), and what the page did after the token
(`challenge_open`, `token_ready`, `rejected_banner`, `url_changed`, `site_accepted`). `captcha_challenge_steps` counts
steps spent with an image grid open. The raw ledger is `results/captcha_spend/ledger.jsonl` on the server unless
`CAPTCHA_SPEND_LEDGER` points elsewhere; it is not in git and is lost when the disk is replaced, so set
`CAPTCHA_SPEND_LEDGER=/var/lib/usersim/captcha_ledger.jsonl` (next to `mcp_accounts`) to keep it across deploys.

## Google sign-in for token callers (`google_signin_token_callers`, off by default)

Products that only let new accounts in through "Continue with Google" stop every simulated user at signup, because
Google's sign-in pages are blocked. `mvp/sim_mcp/google_signin.py` lets sessions of callers **with a valid bearer token**
start with the UserSim signups Google session; anonymous callers never get it and stay blocked.
- State: a Playwright storage_state of the signed-in signups Google account, in a **private** object (never under
  `seed_states/`), `{"storage_state", "seed", "saved_at", "account"}`. The server VM reads it from env
  `MVP_GOOGLE_STATE_URI`.
- The session runs on the seed named in `seed` (the IP Google has seen) when it is free.
- On: set `MVP_GOOGLE_STATE_URI` on the server, then `google_signin_token_callers: true` in limits.json.
- A token client whose token variable is unset sends `Authorization: Bearer ` (empty): the server treats that as no
  token, so a plugin can carry an optional token header.

### Google login by the server (`usersim_google_signin`)

A copied Google session is refused on a new browser and IP, so the server signs in itself. It uses the steps of
`mvp/auto_signin.py`: account chooser, email, password, a TOTP from `totp_secret`, a code emailed to the account
(`app_password`), and phone confirmation.
- Vault: same shape as `secrets/credentials.json`, the Google entry for the UserSim signups account. The server reads
  it from `MVP_GOOGLE_VAULT_URI`, either `gs://.../private/...json` or `sm://projects/<p>/secrets/<name>` (Secret Manager,
  via gcloud). Keep `totp_secret` set so no phone is needed.
- A token session that clicks a product's Google button calls `usersim_google_signin`. The model never sees the
  credentials. Anonymous callers get an error.
