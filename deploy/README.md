# Deploying UserSim

Production is one long-lived FastAPI process on the VM `usersim-grokbot-web`
(static IP 35.202.98.224, HTTPS at https://35-202-98-224.sslip.io via caddy).
https://usersim.vercel.app is only a rewrite proxy to it (`deploy/vercel-proxy`,
deployed with `deploy/vercel_deploy.sh`).

## VM backend

Secrets live in `secrets/env` on the VM (gitignored; template
`scripts/local/env.example`). Start the server with:

```bash
deploy/vm_server.sh          # sources secrets/env, exits if USERSIM_ADMIN_TOKEN is missing
```

`HOST`/`PORT` (default `127.0.0.1:8080`) must match caddy's upstream.

### Required: `USERSIM_ADMIN_TOKEN`

`POST /api/runtime/kill` and studies of UserSim's own site (`admin_dogfood`)
need `Authorization: Bearer $USERSIM_ADMIN_TOKEN`. With no token set, the
server refuses every admin call (403), so set it before deploying:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # add as USERSIM_ADMIN_TOKEN=... in secrets/env
```

Keep the same value in Cursor Cloud Agent secrets (`.env.cloud.example`) and in
the shell of anyone running harnesses: `mvp/e2e2_matrix.py`,
`mvp/e2e_three_studies.py` and `mvp/smoke_first_shot.py` send it on their kill
calls when it is set. Kill by hand:

```bash
curl -X POST -H "Authorization: Bearer $USERSIM_ADMIN_TOKEN" -H 'content-type: application/json' \
  -d '{"agents": true}' https://35-202-98-224.sslip.io/api/runtime/kill
```

If the app itself is ever deployed elsewhere (Cloud Run via `Dockerfile`, or
`MODE=full` on Vercel), set `USERSIM_ADMIN_TOKEN` in that platform's secrets.

### Optional

| Env var | Default | Meaning |
|---|---|---|
| `USERSIM_OWN_HOSTS` | built-in list | Extra UserSim hosts agents must never drive (comma-separated) |
| `USERSIM_OWN_IPS` | `35.202.98.224` | UserSim IPs, for DNS and sslip/nip matching |
| `USERSIM_AGENT_DENY_IPS` | empty | IPs/CIDRs whose study and runtime POSTs get 403 |
| `MVP_MAX_STUDY_STARTS` | `6` | Studies admitted per window; `0` turns the cap off |
| `MVP_STUDY_START_WINDOW_S` | `600` | Window for the start cap |
| `MVP_MAX_CONCURRENT_STUDIES` | `2` | Studies holding browsers at once |
| `MVP_ADMITTED_MAX_AGE_S` | `1800` | An admitted queue entry older than this stops holding a slot |

Harnesses that submit several studies wait out a 429 using its `Retry-After`,
up to `MVP_HARNESS_429_MAX_WAIT_S` (default 900s) in total.
