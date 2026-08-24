# UserSim — internal QA testing tool

Local tool for automated QA testing: give it a target URL + a user profile to test as, and it
spins up parallel QA agents (Gemini 2.5 Flash, driving real local Chromium browsers via
[browser-use](https://github.com/browser-use/browser-use)) that run test cases against the live
site, then reports back issues found, what works, and prioritized fixes. Two ways to run it: a
web UI, or a terminal CLI that streams progress and opens screenshots as they land.

## Setup (once)

```bash
cd UserSim
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r mvp/requirements.txt
.venv/bin/playwright install chromium
gcloud auth login   # if you haven't already
gcloud config set project project-amer-scs-sandbox
```

Auth is Vertex AI via your `gcloud` login (see `src/auth.py`, `src/config.py`) — no API keys
needed. Model and project are set in `src/config.py` (`gemini-2.5-flash`,
`project-amer-scs-sandbox`, `us-central1`).

## Run the web UI

```bash
PYTHONPATH=src .venv/bin/uvicorn mvp.server:app --port 8787
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787), enter a public URL (no login required) and
a customer segment, and submit. The page polls and streams the activity log, per-agent step
trace, and bbox screenshots live.

Known UI quirk: clicking a persona card toggles its trace open/closed — if a screenshot looks
missing, click the card once to make sure the trace is expanded, not collapsed.

## Run the CLI

```bash
.venv/bin/python mvp/cli.py \
  --url "https://www.cloud.com/" \
  --segment "Compliance officer at a global bank evaluating secure access and integration platforms"
```

This prints the activity log live in the terminal, opens a browser **viewer** at
`http://127.0.0.1:8787/?study=<id>` — the exact same UI as the web app, deep-linked straight to
this study (personas, live trace, bbox screenshots, QA report) — and prints the QA report at
the end.

If a UserSim server is already running on `--port` (default 8787), the CLI talks to it directly
over HTTP instead of starting its own — the viewer and the CLI end up watching the same study on
the same server. Only if nothing answers on that port does it start one itself, in-process.

Flags:

| Flag | Default | Meaning |
|---|---|---|
| `--agents` | 4 | Number of persona/task agents to run |
| `--max-steps` | 12 | Max browser-use steps per agent |
| `--browser-concurrency` | 3 | Concurrent local Chromium sessions — **only takes effect if the CLI starts its own server**; an already-running server keeps the concurrency it was started with |
| `--show-browser` | off | Show the Chromium windows instead of headless |
| `--port` | 8787 | UserSim server port — reused if already running |
| `--no-viewer` | off | Don't auto-open the viewer URL in a browser (it still prints) |
| `--poll` | 1.5 | Seconds between progress polls |

For a quick, cheap smoke test: `--agents 1 --max-steps 5`. See the root
[README's coding-agent section](../README.md#running-this-for-a-user-as-a-coding-agent) if
you're an agent running this on someone's behalf rather than a human at a terminal.

## Flow

1. Fetch the page (plain HTTP, falling back to local headless Chromium if blocked — no inferred
   content if both fail).
2. Gemini 2.5 Flash generates 4 personas + 4 on-site tasks grounded in the page's actual content.
3. Each persona's task runs as a real browser-use agent (Gemini 2.5 Flash, local Chromium),
   producing a step-by-step trace with a bbox screenshot per step.
4. Gemini 2.5 Flash turns each recorded trace into friction/strengths feedback, then synthesizes
   all sessions into one executive summary.

## Where things land

Each study writes to `mvp/runs/<study_id>/<agent_id>/`: `screenshots/bbox_N.png` (numbered
clickable elements boxed), `run.json` (full trace + actions), and `conversation/` (the raw
LLM conversation). Nothing here is committed — the whole `mvp/runs/` dir is gitignored.

## Env vars

All optional; set before starting the server or CLI. Note: the CLI always sends `agent_count`,
`max_steps`, and `headless` explicitly in its API request (from `--agents`/`--max-steps`/
`--show-browser`), so `MVP_AGENT_COUNT`/`MVP_MAX_BROWSER_STEPS`/`MVP_BROWSER_HEADLESS` only
govern studies started from the **web UI** (which has no such fields) or a raw API call that
omits them.

| Var | Default | Meaning |
|---|---|---|
| `MVP_AGENT_COUNT` | 4 | Cap on personas/tasks per study |
| `MVP_MAX_BROWSER_STEPS` | 12 | Max browser-use steps per agent |
| `MVP_BROWSER_CONCURRENCY` | 3 | Concurrent local Chromium sessions |
| `MVP_AGENT_CONCURRENCY` | 4 | Concurrent Gemini calls (persona gen / feedback) |
| `MVP_BROWSER_HEADLESS` | true | Set `false` to see the Chromium windows |
| `MVP_LLM_MAX_RETRIES` | 6 | Retries per Gemini call inside a browser-use agent |
