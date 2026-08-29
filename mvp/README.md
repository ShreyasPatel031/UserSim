# UserSim MVP

Local web UI for synthetic user research: URL + segment → generated tasks → parallel persona agents → executive summary.

## Public demo

**https://usersim.vercel.app**

(Vercel snapshot mode — 2 agents, ~20–45s per study. Live Browserbase agents are local-only for now.)

## Run locally (recommended)

Same behavior as production (snapshot agents, sync POST):

```bash
./mvp/vercel_dev.sh
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000).

Requires `MISTRAL_API_KEY` in `secrets/env` or `.env.local`.

## Full local mode (live Browserbase)

```bash
pip install -r mvp/requirements.txt
PYTHONPATH=src uvicorn mvp.server:app --reload --port 8787
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). Needs `BROWSERBASE_API_KEY` (Browserbase free tier may hit minute limits).

Blocked sites (403, WAF, empty JS shells) are retried via Browserbase. If still blocked, the study stops — no inferred fallback.

## Flow

1. User enters a public URL and customer segment.
2. Mistral generates 4 personas and 4 on-site tasks.
3. Four agents run in parallel (page snapshot + persona simulation).
4. Mistral synthesizes friction themes, strengths, and recommendations.

This MVP uses HTTP page snapshots, not live browser agents. Swap in `mistral_browser_use_runner` later for full browsing traces.
