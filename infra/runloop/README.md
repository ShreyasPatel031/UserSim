# UserSim on Runloop + Reflex

This mirrors the GCP video-experiment topology without copying VM credentials:

- one immutable Runloop **Blueprint** replaces repeated GCP package installs;
- twelve parallel Runloop **Devboxes** replace the twelve GCP shard VMs;
- eight Browser Use workers per Devbox preserve the current 96-slot ceiling;
- Runloop account secrets provide GitHub and Google ADC credentials at runtime;
- Reflex wraps the blueprint, repository, runtime, and task prompt as a reusable
  **Persona** and provides session monitoring/suspend/resume.

## 1. Build the reusable blueprint

Install the official Runloop CLI and authenticate it with `RUNLOOP_API_KEY`, then:

```bash
rli blueprint from-dockerfile \
  --name usersim-video-v1 \
  --dockerfile infra/runloop/Dockerfile \
  --build-context .
```

The image contains only Chromium and dependencies. Never put Google login data,
cookies, phone numbers, TOTP seeds, or API credentials in the build context.

## 2. Configure Runloop secrets

Create these in Runloop Dashboard -> Settings -> Secrets:

- `USERSIM_GITHUB_TOKEN`: repository read access only.
- `USERSIM_GOOGLE_ADC_JSON`: a least-privilege Google service-account JSON with
  Vertex AI invocation permission.

The launcher maps them to environment variables only for the lifetime of each
Devbox. An authenticated YouTube browser profile must be supplied to dedicated
trusted seed Devboxes; it must not be copied into the blueprint or shared by all
workers concurrently.

## 3. Run a gate before the full experiment

```bash
uv pip install runloop_api_client
export RUNLOOP_API_KEY=...
export USERSIM_REPO_URL=https://github.com/OWNER/UserSim.git
python scripts/runloop/launch_video_fleet.py --shards 1 --workers 4
```

After the four-worker gate passes task-level validation, launch the matching
twelve-shard topology:

```bash
python scripts/runloop/launch_video_fleet.py --shards 12 --workers 8
```

Devboxes shut down automatically. Pass `--keep` only for deliberate debugging.

## 4. Create the Reflex Persona

In Reflex, create a Persona named `UserSim Video Researcher` with:

- repository: UserSim;
- blueprint: `usersim-video-v1`;
- agent runtime: Codex;
- validation command: the four-worker gate above;
- completion rule: every task has content evidence and YouTube workers have an
  avatar/account signal in the same agent-controlled browser;
- no automatic full-fleet trigger until the gate succeeds.

Save the calibrated session as the Persona, then use parallel Persona sessions
for the full experiment. Reflex is the operational layer; Runloop owns the
Devbox lifecycle and isolation.
