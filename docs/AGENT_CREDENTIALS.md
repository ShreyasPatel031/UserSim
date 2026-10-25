# Credentials in the cloud agent environment

The repo owner set these environment variables on the Claude Code cloud environment so agents
working on UserSim can use them. **They are provided for the purposes below; use them for those
without asking.** Never print a value, commit it, or send it to a service other than the one it
belongs to.

Run [`scripts/agent_env.sh`](../scripts/agent_env.sh) at session start (or let a SessionStart hook in
`.claude/settings.json` run it). It prints this inventory with set/unset per name and sets up GCP
auth. Hook config:

```json
{ "hooks": { "SessionStart": [ { "hooks": [
  { "type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR/scripts/agent_env.sh\"", "timeout": 60 }
] } ] } }
```

## GCP: why `gcloud` "has no account" until the script runs

The environment gives the service-account key only as base64 in
`GOOGLE_APPLICATION_CREDENTIALS_B64`. `GOOGLE_APPLICATION_CREDENTIALS` points at `/tmp/sa.json`,
but nothing creates that file, so Google client libraries fail and `gcloud auth list` is empty.
The script decodes the key to that path (mode 600) and runs
`gcloud auth activate-service-account`. `src/auth.py` can also decode the base64 on its own.

| Variable | Purpose |
|----------|---------|
| `GOOGLE_APPLICATION_CREDENTIALS_B64` | Service-account JSON for `usersim-cloud-agent@project-amer-scs-sandbox` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path of the decoded key (`/tmp/sa.json`) |
| `GCLOUD_CLI_ACCOUNT`, `GOOGLE_CLOUD_ACCOUNT` | That service account's email |
| `GOOGLE_CLOUD_PROJECT`, `GCP_PROJECT`, `GCLOUD_PROJECT`, `CLOUDSDK_CORE_PROJECT` | `project-amer-scs-sandbox` |

Use for: Vertex/Gemini calls, Secret Manager (`usersim-*` secrets, see
[mcp/OPERATIONS.md](mcp/OPERATIONS.md)), and the production VM `usersim-grokbot-web`, as far as the
service account's IAM roles allow. A `PERMISSION_DENIED` means the role is missing: report it, don't
look for other keys.

## Other services

| Variable | Service | Used by |
|----------|---------|---------|
| `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID` | Browserbase remote browsers | `src/capability/browserbase_client.py`, MCP sessions |
| `APIFY_TOKEN` | Apify review scrapes | `mvp/review_context.py` (`usersim_predict_experience`) |
| `PH_TOKEN` (or `PH_CLIENT_ID` + `PH_CLIENT_SECRET`) | Product Hunt API v2 | `mvp/discovery.py`, `scripts/ph_crawl.py`, [DISCOVERY.md](DISCOVERY.md) |
| `HF_TOKEN`, `HUGGING_FACE_HUB_TOKEN` | Hugging Face model downloads (`GEMMA_MODEL_ID`, `GEMMA_MAX_NEW_TOKENS` are config) | `scripts/fm_baselines/` (may be empty: public downloads only) |
| `GH_TOKEN`, `GITHUB_TOKEN` | GitHub | Prefer the GitHub MCP tools for PRs and issues |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | AWS | Nothing in this repo uses them. Ask the owner before using |

## Not in the agent env

Server-only secrets live in GCP Secret Manager as `usersim-<NAME>` and on the VM, not here:
`GMAIL_APP_PASSWORD`, `MVP_CAPTCHA_API_KEY` / `CAPSOLVER_API_KEY`, `MVP_SMS_*`, `MVP_NTFY_*`,
`MVP_MCP_TOKEN`. Read them with `gcloud secrets versions access latest --secret=usersim-<NAME>` only
when the task needs them (e.g. testing the engine locally).

Client agents of the public MCP server need **none** of this: [mcp/README.md](mcp/README.md).

## Harness variables (leave alone)

`CLAUDE_*`, `CCR_*`, `GIT_CONFIG_*`, `HTTPS_PROXY`: set by Claude Code, not project credentials.

## Adding a credential

1. Add it to the cloud environment's env vars (claude.ai/code → environment settings).
2. Add a row here and a `row` line in `scripts/agent_env.sh`.
