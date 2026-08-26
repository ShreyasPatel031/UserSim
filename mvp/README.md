# UserSim MVP

Synthetic user research: URL + customer segment → personas → parallel agents → friction map + executive summary.

**Public demo:** https://usersim.vercel.app

---

## Run locally (open in your browser)

### 1. Prerequisites

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r mvp/requirements.txt
pip install -r requirements.txt   # Mistral + optional Browserbase deps
```

### 2. API keys

Create `secrets/env` (gitignored):

```bash
MISTRAL_API_KEY=your_key_here
MISTRAL_MODEL=mistral-small-2603
```

Optional for live browser mode only:

```bash
BROWSERBASE_API_KEY=bb_live_...
BROWSERBASE_PROJECT_ID=...
```

### 3. Start the server

**Recommended** — same as production (snapshot agents, ~20–45s per study):

```bash
./mvp/vercel_dev.sh
```

**Alternative** — async mode (returns immediately, UI polls progress):

```bash
./mvp/run.sh
```

### 4. Open the UI

In your browser:

| Mode | URL |
|------|-----|
| Vercel-mode (recommended) | http://127.0.0.1:3000 |
| Async local | http://127.0.0.1:8787 |

Enter a public URL and customer segment, click run, and watch persona cards fill in.

### 5. Quick smoke test (optional)

```bash
./mvp/run_smoke.sh
```

Polls until complete or fails after 60s.

---

## Modes

| | `./mvp/vercel_dev.sh` | `./mvp/run.sh` |
|---|---|---|
| Port | 3000 | 8787 |
| Study API | Sync (waits for result) | Async (poll `/api/studies/{id}`) |
| Agents | Snapshot (no live browser) | Snapshot by default; live if Browserbase configured |
| Matches production | Yes | No |

Snapshot mode reads the page over HTTP and simulates personas with Mistral — fast, no Browserbase quota needed.

---

## Live browser window (optional)

To run agents in a real Chromium session via Browserbase (slow, 5+ min, needs credits):

```bash
source secrets/env
unset VERCEL
export MVP_QUICK=0
export MVP_AGENT_COUNT=4
PYTHONPATH=src .venv/bin/uvicorn mvp.server:app --reload --port 8787
```

Open http://127.0.0.1:8787. Requires `BROWSERBASE_API_KEY`.

---

## Troubleshooting

**Port already in use**

```bash
lsof -i :3000          # find process
kill <pid>             # stop it, then restart ./mvp/vercel_dev.sh
```

**`MISTRAL_API_KEY` not set** — add it to `secrets/env` or export before starting.

**Study fails with Browserbase 402** — free tier minutes exhausted; use `./mvp/vercel_dev.sh` (snapshot mode, no Browserbase).

**`vercel dev` broken locally** — use `./mvp/vercel_dev.sh` instead. It runs uvicorn with the same env as production.

---

## What happens on a run

1. Fetch page content from the URL you entered.
2. Mistral generates personas and on-site tasks grounded in that content.
3. Agents run in parallel (snapshot simulation on Vercel-mode; optional live browser locally).
4. Mistral writes an executive summary: friction themes, quotes, recommendations.
