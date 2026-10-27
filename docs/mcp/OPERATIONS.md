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
| ~~`APIFY_TOKEN`~~ | Not in Secret Manager (every VM user can reach it via the metadata server): the Apify token and the residential proxy live only in the fetch gateway's `/etc/fetchgate/credentials.env` (`docs/discovery/FETCH_LADDER.md`) |
| `MVP_SMS_PHONE` | Owner phone (E.164) used for SMS verification |
| `MVP_OWNER_PHONE` | Optional owner phone metadata |
| `MVP_NTFY_SMS_TOPIC` | ntfy topic where the phone forwards SMS (sensitive) |
| `MVP_NTFY_TOKEN` | Bearer token for private ntfy |
| `MVP_SMS_API_KEY` | TextVerified (or other) SMS API key |
| `MVP_MCP_TOKEN` | Optional bearer token(s) that skip anonymous caps |
| `MVP_TEXTVERIFIED_API_KEY` | Legacy TextVerified key name |

Non-secret config (URLs, project ids, feature toggles that are not credentials) may remain in `/etc/usersim/env` or move to `limits.json` when appropriate.

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
