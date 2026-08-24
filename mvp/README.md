# UserSim — AI testing agent

Local tool for synthetic user testing: give it a public URL + a customer segment, and it
spins up parallel AI testing agents (Gemini 2.5 Flash, driving real local Chromium browsers via
[browser-use](https://github.com/browser-use/browser-use)) that browse the live site, then
returns friction maps, quotes, and an executive summary. Two ways to run it: a web UI, or a
terminal CLI that streams progress and opens screenshots as they land.

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
PYTHONPATH=src .venv/bin/python mvp/cli.py \
  --url "https://www.python.org" \
  --segment "students new to programming who want to download Python and find a beginner tutorial"
```

This prints the activity log live and opens each step screenshot (macOS `open` / Linux
`xdg-open`) as soon as it's captured, then prints the executive summary at the end.

Flags:

| Flag | Default | Meaning |
|---|---|---|
| `--agents` | 4 | Number of persona/task agents to run |
| `--max-steps` | 12 | Max browser-use steps per agent |
| `--browser-concurrency` | 3 | Concurrent local Chromium sessions |
| `--show-browser` | off | Show the Chromium windows instead of headless |
| `--no-open` | off | Don't auto-open each screenshot as it lands |
| `--poll` | 1.5 | Seconds between progress polls |

For a quick, cheap smoke test: `--agents 1 --max-steps 5`.

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

All optional; set before starting the server or CLI:

| Var | Default | Meaning |
|---|---|---|
| `MVP_AGENT_COUNT` | 4 | Cap on personas/tasks per study |
| `MVP_MAX_BROWSER_STEPS` | 12 | Max browser-use steps per agent |
| `MVP_BROWSER_CONCURRENCY` | 3 | Concurrent local Chromium sessions |
| `MVP_AGENT_CONCURRENCY` | 4 | Concurrent Gemini calls (persona gen / feedback) |
| `MVP_BROWSER_HEADLESS` | true | Set `false` to see the Chromium windows |
| `MVP_LLM_MAX_RETRIES` | 6 | Retries per Gemini call inside a browser-use agent |
